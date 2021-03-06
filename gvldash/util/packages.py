from abc import abstractmethod
from contextlib import closing
import importlib
import os
import urllib2
from urlparse import urlparse

from bioblend.cloudman import CloudManInstance
from package_helpers import get_cluster_password, get_registry_location
import services
import util
import yaml


def str_to_class(fq_class_name):
    parts = fq_class_name.rsplit('.', 1)
    module_name = parts[0]
    class_name = parts[1]

    module_ = importlib.import_module(module_name)
    class_ = getattr(module_, class_name)
    return class_


class Package(object):

    service_name = None
    display_name = None
    description = None
    service_process = None
    service_path = None
    parameters = None

    def __init__(
            self, package_name, display_name, description, services, parameters):
        self.package_name = package_name
        self.display_name = display_name
        self.description = description
        self.services = services
        self.parameters = parameters or {}

    def get_package_data(self):
        data = {}
        data['package_name'] = self.package_name
        data['display_name'] = self.display_name
        data['description'] = self.description
        data['services'] = self.services
        data['parameters'] = self.parameters
        data['status'] = self.get_package_status()
        return data

    def get_package_status(self):
        if self.is_installed():
            return "installed"
        elif self.is_installing():
            return "installing"
        else:
            return "not_installed"

    def set_package_status(self, new_status):
        if new_status == "installed":
            if self.is_installed():
                raise Exception("Package already installed")
            elif self.is_installing():
                raise Exception("Package currently being installed")
            else:
                return self.install_package()
        elif new_status == "not_installed":
            if self.is_installed():
                raise Exception("Uninstallation is currently not supported")
            elif self.is_installing():
                raise Exception(
                    "Package is currently being installed. Cancellation not supported.")
            else:
                raise Exception("Cannot uninstall. Package is not installed.")
        else:
            raise Exception("Unsupported operation: {0}", new_status)

    def install_package(self):
        if not self.is_installing():
            self.install()
            for service in self.services:
                services.add_service(services.dict_to_service(service))

    @abstractmethod
    def is_installed(self):
        raise Exception("Not implemented")

    @abstractmethod
    def is_installing(self):
        raise Exception("Not implemented")

    @abstractmethod
    def install(self):
        raise Exception("Not implemented")


class GalaxyPackage(Package):
    cm_instance = CloudManInstance(
        "http://127.0.0.1:42284",
        get_cluster_password())

    def is_installed(self):
        try:
            cluster_info = self.cm_instance.get_cluster_type()
            if cluster_info and cluster_info['cluster_type'] == "Galaxy":
                return True
        except Exception:
            pass
        return False

    def is_installing(self):
        try:
            if self.cm_instance.get_cluster_type() and self.cm_instance.get_galaxy_state() in (
                    "Unstarted", "Starting"):
                return True
        except Exception:
            pass
        return False

    def install(self):
        return self.cm_instance.initialize(
            "Galaxy", galaxy_data_option="transient")


class ShellScriptPackage(Package):

    def _get_script_name(self):
        """
        Get the name portion only of the install script.
        E.g:
        If install script url is:
        https://swift.rc.nectar.org.au:8888/v1/AUTH_377/cloudman-gvl-400/packages/install_cmdlineutils_package.sh
        returns:
        install_cmdlineutils_package
        """
        parsed_url = urlparse(self.parameters.get('install_script_url'))
        filename, _ = os.path.splitext(
            os.path.basename(parsed_url.path))
        return filename

    def is_installed(self):
        return os.path.exists(
            "/opt/gvl/info/{}".format(self.parameters.get('install_version_data')))

    def is_installing(self):
        return util.is_process_running(self._get_script_name())

    def install(self):
        return util.run_async(
            "sudo sh -c 'wget --output-document=/tmp/{0} {1} && sh /tmp/{0}'".format(self._get_script_name(), self.parameters.get('install_script_url')))


def load_package_registry():
    if os.path.isfile("package_registry.yml"):
        package_file = open("package_registry.yml", 'r')
    else:
        package_file = closing(
            urllib2.urlopen(get_registry_location()))
    with package_file as stream:
        registry = yaml.load(stream)
        package_list = [str_to_class(pkg['implementation_class'])(pkg['name'], pkg['display_name'], pkg['description'], pkg['services'], pkg.get('parameters', {}))
                        for pkg in registry['packages']]
        return package_list

package_list = load_package_registry()


def get_packages():
    data = []
    for package in package_list:
        data.append(package.get_package_data())
    return data


def get_package_data(package_name):
    for package in package_list:
        if package.package_name == package_name:
            return package.get_package_data()


def install_package(package_name):
    for package in package_list:
        if package.package_name == package_name:
            return package.install_package()
