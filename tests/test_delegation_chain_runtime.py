"""
tests.test_delegation_chain_runtime — DelegationChain运行时验证测试

测试覆盖：
1. 树形结构构建和索引
2. find_path()路径查找
3. validate_tree()树形验证
4. _compute_effective_contract()叠加计算
5. _merge_contracts_strict()交集合并
6. hook.py集成：每次调用都执行链级验证

v0.48.0 — P1 Architecture: DelegationChain runtime validation
"""
import pytest
from ystar.kernel.dimensions import DelegationContract, DelegationChain, IntentContract


class TestDelegationChainTree:
    """DelegationChain树形结构测试"""

    def test_tree_structure_build(self):
        """测试树形结构构建和索引"""
        # 构建：CEO -> CTO -> eng-kernel
        #            -> CMO
        root = DelegationContract(
            principal="system",
            actor="CEO",
            contract=IntentContract(name="ceo_root"),
            action_scope=[],
            children=[],
        )

        cto = DelegationContract(
            principal="CEO",
            actor="CTO",
            contract=IntentContract(name="cto", deny=["rm -rf"]),
            action_scope=["Read", "Write", "Bash"],
            children=[],
        )

        eng_kernel = DelegationContract(
            principal="CTO",
            actor="eng-kernel",
            contract=IntentContract(name="eng_kernel", deny=["rm -rf", "sudo"]),
            action_scope=["Read", "Write"],
            children=[],
        )

        cmo = DelegationContract(
            principal="CEO",
            actor="CMO",
            contract=IntentContract(name="cmo"),
            action_scope=["Read"],
            children=[],
        )

        cto.children.append(eng_kernel)
        root.children.extend([cto, cmo])

        chain = DelegationChain(root=root)

        # 验证索引构建
        assert "CEO" in chain.all_contracts
        assert "CTO" in chain.all_contracts
        assert "eng-kernel" in chain.all_contracts
        assert "CMO" in chain.all_contracts

    def test_find_path(self):
        """测试路径查找"""
        # 构建简单链：CEO -> CTO -> eng-kernel
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo"),
            action_scope=[],
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto"),
                    action_scope=["Read", "Write"],
                    children=[
                        DelegationContract(
                            principal="CTO", actor="eng-kernel",
                            contract=IntentContract(name="kernel"),
                            action_scope=["Read"],
                            children=[],
                        )
                    ],
                )
            ],
        )

        chain = DelegationChain(root=root)

        # 查找eng-kernel的路径
        path = chain.find_path("eng-kernel")

        assert len(path) == 3
        assert path[0].actor == "CEO"
        assert path[1].actor == "CTO"
        assert path[2].actor == "eng-kernel"

    def test_find_path_not_found(self):
        """测试路径查找：agent不存在"""
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo"),
            action_scope=[],
            children=[],
        )

        chain = DelegationChain(root=root)
        path = chain.find_path("NonExistent")

        assert path == []

    def test_validate_tree_monotonicity_action_scope(self):
        """测试树形验证：action_scope单调性检查"""
        # 违反单调性：子节点权限超出父节点
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["rm"]),
            action_scope=["Read"],  # 只授权Read
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto"),
                    action_scope=["Read", "Write", "Bash"],  # 超出授权！
                    children=[],
                )
            ],
        )

        chain = DelegationChain(root=root)
        valid, violations = chain.validate_tree()

        assert not valid
        assert any("action_scope exceeds" in v for v in violations)

    def test_validate_tree_monotonicity_contract(self):
        """测试树形验证：contract单调性检查"""
        # 违反单调性：子节点contract不包含父节点的deny
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["rm -rf", "sudo"]),
            action_scope=["Read", "Write"],
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto", deny=["rm -rf"]),  # 缺少sudo！
                    action_scope=["Read"],
                    children=[],
                )
            ],
        )

        chain = DelegationChain(root=root)
        valid, violations = chain.validate_tree()

        assert not valid
        assert any("contract exceeds" in v for v in violations)

    def test_validate_tree_cycle_detection(self):
        """测试树形验证：循环检测"""
        # 手动创建循环（正常情况下不应该发生，但测试防御性）
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo"),
            action_scope=[],
            children=[],
        )

        # 创建一个子节点，其actor与root相同（造成循环）
        cycle_child = DelegationContract(
            principal="CEO", actor="CEO",  # 循环！
            contract=IntentContract(name="ceo_cycle"),
            action_scope=[],
            children=[],
        )

        root.children.append(cycle_child)
        chain = DelegationChain(root=root)
        valid, violations = chain.validate_tree()

        assert not valid
        assert any("Cycle detected" in v for v in violations)

    def test_validate_tree_valid_structure(self):
        """测试树形验证：正确的树形结构"""
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["rm -rf"]),
            action_scope=["Read", "Write", "Bash"],
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto", deny=["rm -rf", "sudo"]),
                    action_scope=["Read", "Write"],
                    children=[
                        DelegationContract(
                            principal="CTO", actor="eng-kernel",
                            contract=IntentContract(name="kernel", deny=["rm -rf", "sudo", "DROP"]),
                            action_scope=["Read"],
                            children=[],
                        )
                    ],
                ),
                DelegationContract(
                    principal="CEO", actor="CMO",
                    contract=IntentContract(name="cmo", deny=["rm -rf"]),
                    action_scope=["Read"],
                    children=[],
                ),
            ],
        )

        chain = DelegationChain(root=root)
        valid, violations = chain.validate_tree()

        assert valid
        assert violations == []


class TestEffectiveContractComputation:
    """有效contract计算测试"""

    def test_merge_contracts_strict_deny(self):
        """测试contract交集合并：deny取并集"""
        from ystar.adapters.hook import _merge_contracts_strict

        c1 = IntentContract(name="parent", deny=["rm"])
        c2 = IntentContract(name="child", deny=["sudo"])

        merged = _merge_contracts_strict(c1, c2)

        # deny取并集
        assert "rm" in merged.deny
        assert "sudo" in merged.deny

    def test_merge_contracts_strict_only_paths(self):
        """测试contract交集合并：only_paths取交集"""
        from ystar.adapters.hook import _merge_contracts_strict

        c1 = IntentContract(
            name="parent",
            only_paths=["/home/user"],
        )

        c2 = IntentContract(
            name="child",
            only_paths=["/home/user/project"],
        )

        merged = _merge_contracts_strict(c1, c2)

        # only_paths取交集（更窄的路径）
        assert "/home/user/project" in merged.only_paths

    def test_merge_contracts_strict_value_range(self):
        """测试contract交集合并：value_range取更严格的"""
        from ystar.adapters.hook import _merge_contracts_strict

        c1 = IntentContract(
            name="parent",
            value_range={"file_size": {"max": 1000}}
        )

        c2 = IntentContract(
            name="child",
            value_range={"file_size": {"max": 500}}
        )

        merged = _merge_contracts_strict(c1, c2)

        # 取更小的max（更严格）
        assert merged.value_range["file_size"]["max"] == 500

    def test_compute_effective_contract(self):
        """测试叠加contract计算"""
        from ystar.adapters.hook import _compute_effective_contract

        # 构建chain
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["rm -rf"]),
            action_scope=[],
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto", deny=["sudo"]),
                    action_scope=["Read", "Write"],
                    children=[],
                )
            ],
        )

        chain = DelegationChain(root=root)
        chain_dict = chain.to_dict()

        # 计算CTO的有效contract
        effective = _compute_effective_contract(chain_dict, "CTO")

        # 应该包含CEO和CTO的叠加约束
        contract = IntentContract.from_dict(effective)
        assert "rm -rf" in contract.deny
        assert "sudo" in contract.deny

    def test_compute_effective_contract_deep_path(self):
        """测试叠加contract计算：深层路径"""
        from ystar.adapters.hook import _compute_effective_contract

        # 构建三层链：CEO -> CTO -> eng-kernel
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["rm -rf"]),
            action_scope=[],
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto", deny=["sudo"]),
                    action_scope=["Read", "Write"],
                    children=[
                        DelegationContract(
                            principal="CTO", actor="eng-kernel",
                            contract=IntentContract(name="kernel", deny=["DROP"]),
                            action_scope=["Read"],
                            children=[],
                        )
                    ],
                )
            ],
        )

        chain = DelegationChain(root=root)
        chain_dict = chain.to_dict()

        # 计算eng-kernel的有效contract
        effective = _compute_effective_contract(chain_dict, "eng-kernel")

        # 应该包含所有三层的约束
        contract = IntentContract.from_dict(effective)
        assert "rm -rf" in contract.deny
        assert "sudo" in contract.deny
        assert "DROP" in contract.deny


class TestSerializationDeserialization:
    """序列化/反序列化测试"""

    def test_delegation_contract_with_children_roundtrip(self):
        """测试DelegationContract包含children的序列化往返"""
        parent = DelegationContract(
            principal="CEO",
            actor="CTO",
            contract=IntentContract(name="cto", deny=["rm"]),
            action_scope=["Read", "Write"],
            children=[
                DelegationContract(
                    principal="CTO",
                    actor="eng-kernel",
                    contract=IntentContract(name="kernel", deny=["rm", "sudo"]),
                    action_scope=["Read"],
                    children=[],
                )
            ],
        )

        # Serialize
        data = parent.to_dict()

        # Verify children is serialized
        assert "children" in data
        assert len(data["children"]) == 1
        assert data["children"][0]["actor"] == "eng-kernel"

        # Deserialize
        restored = DelegationContract.from_dict(data)

        # Verify structure is preserved
        assert restored.actor == "CTO"
        assert len(restored.children) == 1
        assert restored.children[0].actor == "eng-kernel"
        assert "sudo" in restored.children[0].contract.deny

    def test_delegation_chain_tree_roundtrip(self):
        """测试DelegationChain树形结构的序列化往返"""
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["rm -rf"]),
            action_scope=[],
            children=[
                DelegationContract(
                    principal="CEO", actor="CTO",
                    contract=IntentContract(name="cto", deny=["rm -rf", "sudo"]),
                    action_scope=["Read", "Write"],
                    children=[],
                ),
                DelegationContract(
                    principal="CEO", actor="CMO",
                    contract=IntentContract(name="cmo", deny=["rm -rf"]),
                    action_scope=["Read"],
                    children=[],
                ),
            ],
        )

        chain = DelegationChain(root=root)

        # Serialize
        data = chain.to_dict()

        # Verify root is serialized
        assert "root" in data
        assert data["root"]["actor"] == "CEO"
        assert len(data["root"]["children"]) == 2

        # Deserialize
        restored = DelegationChain.from_dict(data)

        # Verify tree structure is preserved
        assert restored.root is not None
        assert restored.root.actor == "CEO"
        assert len(restored.root.children) == 2

        # Verify index was rebuilt
        assert "CTO" in restored.all_contracts
        assert "CMO" in restored.all_contracts

    def test_delegation_chain_backward_compatibility(self):
        """测试向后兼容：支持旧的links格式"""
        # Old format: linear chain
        old_data = {
            "links": [
                {
                    "principal": "system",
                    "actor": "CEO",
                    "contract": {"name": "ceo", "deny": ["rm"]},
                    "action_scope": [],
                }
            ]
        }

        # Should still deserialize without error
        chain = DelegationChain.from_dict(old_data)

        # Verify legacy linear chain is preserved
        assert len(chain.links) == 1
        assert chain.links[0].actor == "CEO"

        # root should be None (not tree mode)
        assert chain.root is None


class TestIntegration:
    """集成测试：测试hook.py中的运行时验证"""

    def test_hook_uses_tree_delegation_chain(self, tmp_path, monkeypatch):
        """测试hook在树形delegation_chain模式下正确计算effective contract"""
        # 这是一个框架测试，实际运行需要完整的session环境
        # 在真实场景中，hook会从session.json加载delegation_chain并计算effective contract

        from ystar.adapters.hook import _compute_effective_contract

        # 模拟session.json中的delegation_chain
        root = DelegationContract(
            principal="system", actor="CEO",
            contract=IntentContract(name="ceo", deny=["/etc"]),
            action_scope=[],
            children=[
                DelegationContract(
                    principal="CEO", actor="engineer",
                    contract=IntentContract(name="engineer", deny=["/etc", "/root"]),
                    action_scope=["Read", "Write"],
                    children=[],
                )
            ],
        )

        chain = DelegationChain(root=root)
        chain_dict = chain.to_dict()

        # 计算engineer的effective contract
        effective = _compute_effective_contract(chain_dict, "engineer")

        # 验证effective contract包含路径上所有约束
        contract = IntentContract.from_dict(effective)
        assert "/etc" in contract.deny
        assert "/root" in contract.deny


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
