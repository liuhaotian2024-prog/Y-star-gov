from setuptools import setup, find_packages

setup(
    name="ystar",
    version="0.48.0",
    description="Runtime Governance Framework for AI Agents",
    long_description=open("README.md").read() if __import__("pathlib").Path("README.md").exists() else "",
    long_description_content_type="text/markdown",
    author="Haotian Liu",
    author_email="liuhaotian2024@gmail.com",
    license="MIT",
    python_requires=">=3.11",
    packages=find_packages(exclude=["tests*"]),
    package_data={
        "ystar": [
            "templates/*",
            "policy-builder.html",
            "module_graph/PATH_A_AGENTS.md",
            "domains/pharma/*.py",
            "domains/finance/*.py",
        ],
    },
    entry_points={
        "console_scripts": [
            "ystar=ystar._cli:main",
        ],
    },
    install_requires=[],  # 零外部依赖
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
    ],
)
