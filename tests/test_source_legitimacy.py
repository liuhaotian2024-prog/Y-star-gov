# Layer: Foundation (Test)
"""
Test source legitimacy verification in contract provider.

Task #4: Verify that hash verification detects tampering and passes clean contracts.
"""
from ystar.kernel.contract_provider import ConstitutionProvider
from ystar.kernel.compiler import compile_constitution
import tempfile
import os


def test_verify_hash_detects_tampering():
    """Verify that verify_hash detects source tampering."""
    provider = ConstitutionProvider()

    # Create a temporary contract file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Test Constitution\n\nIntent: test_function\nDeny: malicious_content\n")
        temp_path = f.name

    try:
        # First resolution - establishes hash
        bundle1 = provider.resolve(temp_path)
        original_hash = bundle1.source_hash

        # Tamper with source
        with open(temp_path, 'w') as f:
            f.write("# Test Constitution\n\nIntent: test_function\nDeny: different_content\n")

        # Clear cache and re-read
        provider.invalidate_cache(temp_path)
        bundle2 = provider.resolve(temp_path)

        # Hashes should differ
        assert bundle2.source_hash != original_hash

        # verify_hash should return False when checking against original
        assert not provider.verify_hash(temp_path, original_hash)

        # verify_hash should return True when checking against new hash
        assert provider.verify_hash(temp_path, bundle2.source_hash)

    finally:
        os.unlink(temp_path)


def test_verify_hash_passes_clean():
    """Verify that verify_hash passes for untampered contracts."""
    provider = ConstitutionProvider()

    # Create a temporary contract file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Test Constitution\n\nIntent: test_function\nDeny: malicious_content\n")
        temp_path = f.name

    try:
        # Resolve contract
        bundle = provider.resolve(temp_path)

        # verify_hash should pass with correct hash
        assert provider.verify_hash(temp_path, bundle.source_hash)

        # Re-resolve should still pass
        provider.invalidate_cache(temp_path)
        bundle2 = provider.resolve(temp_path)
        assert provider.verify_hash(temp_path, bundle2.source_hash)

        # Hashes should match (no tampering)
        assert bundle.source_hash == bundle2.source_hash

    finally:
        os.unlink(temp_path)
