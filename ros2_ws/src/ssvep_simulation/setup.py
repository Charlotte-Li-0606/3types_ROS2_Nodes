from setuptools import find_packages, setup

package_name = "ssvep_simulation"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/simulation.launch.py"]),
        (f"share/{package_name}/config", ["config/default.yaml"]),
    ],
    install_requires=["setuptools", "numpy"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "eeg_driver = ssvep_simulation.eeg_driver:main",
            "ssvep_stimulus = ssvep_simulation.ssvep_stimulus:main",
            "ssvep_decoder = ssvep_simulation.ssvep_decoder:main",
        ],
    },
)
