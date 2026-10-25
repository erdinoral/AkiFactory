"""AkiFactory — Turkce kisa video studyosu."""

from setuptools import find_packages, setup

setup(
    name="akifactory",
    version="2.0.0",
    description="AkiFactory — kisa dikey video uretimi",
    python_requires=">=3.11,<3.13",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "fastapi>=0.115.0",
        "uvicorn>=0.32.0",
        "httpx>=0.27.0",
        "pywebview>=5.0",
        "turkish-deasciifier @ git+https://github.com/emres/turkish-deasciifier.git",
    ],
    extras_require={
        "engine": [],  # Tam bagimliliklar: pip install -r requirements.txt
    },
)
