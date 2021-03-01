from setuptools import setup, find_packages
setup(
    name="sergant_hartman",
    install_requires=["attrs", "hyperlink", "Klein", "Twisted", "treq"],
    package_dir={"": "src"},
    packages=find_packages("src") + ["twisted.plugins"],
)
