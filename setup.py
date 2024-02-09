import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pyenasolar",
    version="0.1.6",
    author="geustace",
    author_email="glen@eustace.nz",
    description="Library to communicate with EnaSolar inverters",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/geustace/pyenasolar",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)
