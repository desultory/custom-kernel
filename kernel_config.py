#!/usr/bin/env python3
"""
Used to create kernel configuration files for specific hardware configurations
"""

__version__ = "0.2.0"

from zen_custom import class_logger, handle_plural

from collections import OrderedDict
from enum import Enum

import re


class KConfigSubtype(type):
    """
    Metaclass for KConfigParameter, used to return the correct subtype on creation
    """
    def __call__(cls, *args, **kwargs):
        """
        Returns the correct subtype based on either the type parameter or the config line
        """
        if 'type' not in kwargs and not args:
            return super().__call__(*args, **kwargs)

        if 'type' in kwargs:
            t = kwargs.pop('type')
            return getattr(KConfigTypes, t).value(*args, **kwargs)

        for t in KConfigTypes:
            if match := re.search(t.value.start_regex, args[0]):
                # Remove the first argument, which is the config line
                args = args[1:]
                if prompt := match.group(1):
                    kwargs['value'] = prompt
                return t.value(*args, **kwargs)
        return super().__call__(*args, **kwargs)


def parse_with_type(cls):
    """
    Decorator for KConfigParameter subclasses, adds variable parsing functionality
    """
    class KConfigParameterWithType(cls):
        _variable_type_regex = r'^\s*{var_type}\s*"?(.+)(?:")$'
        variable_types = ['string', 'bool', 'tristate']

        def _init_parameters(self):
            """
            Custom init_parameters extention for KConfigParameterWithType
            """
            super()._init_parameters()
            self.parameters['variable_type'] = None

        def process_line(self, config_line):
            """
            Process the config line, handling variables
            """
            # First use the super function
            super_result = super().process_line(config_line)

            self.logger.debug("Attempting to process type information: %s" % config_line)
            # Check if the line contains a variable type
            for var_type in self.variable_types:
                re_str = self._variable_type_regex.format(var_type=var_type)
                self.logger.debug("Compiled regex: %s" % re_str)
                if match := re.search(re_str, config_line):
                    self.logger.debug("Found variable type: %s" % var_type)
                    self.variable_type = var_type
                    if value := match.group(1):
                        self.logger.debug("Found variable value: %s" % value)
                        self.value = value
                    return True
            return super_result

    KConfigParameterWithType.__name__ = cls.__name__

    return KConfigParameterWithType


@class_logger
class KConfigParameter(metaclass=KConfigSubtype):
    """
    Abstraction of a general KConfig Parameter
    """
    def _init_parameters(self):
        """
        Initializes self.parameters, extended by subclasses
        """
        self.parameters = {'default': None,
                           'value': None}

    def __init__(self, *args, **kwargs):
        """
        Creates a KConfigParameter object
        """
        self._init_parameters()

        for parameter in self.parameters:
            if parameter in kwargs:
                setattr(self, parameter, kwargs.pop(parameter))
            else:
                setattr(self, parameter, self.parameters[parameter])

    def process_line(self, config_line):
        """
        Parses a line from a KConfig file
        """
        self.logger.debug("Attempting to process line: %s" % config_line)
        return False

    def __str__(self):
        """
        Returns a string representation of the KConfigParameter
        """
        out_str = f"{self.__class__.__name__}: "
        (out_str.append(getattr(self, parameter)) for parameter in self.parameters if parameter)
        return out_str


class KConfigChoice(KConfigParameter):
    """
    Abstraction of a linux kernel KConfig choice option
    """
    # Choices start with "choice" followed by nothing, or the choice name
    # Captures the prompt name if present
    start_regex = r'choice\s*(.+)*'
    end_regex = '^endchoice.*$'


class KConfigMenu(KConfigParameter):
    """
    Abstraction of a linux kernel KConfig menu option
    """
    # Menus start with "menu" followed by nothing, or the menu name
    # Captures the prompt name if present
    start_regex = r'^menu\s*(.+)*$'
    end_regex = '^endmenu.*$'


@parse_with_type
class KConfigMenuconfig(KConfigParameter):
    """
    Abstraction of a linux kernel KConfig menuconfig option
    """
    # Menuconfigs start with "menuconfig" followed by nothing, or the menuconfig name
    # Captures the prompt name if present
    start_regex = r'menuconfig\s*(.+)*'


@parse_with_type
class KConfigConfig(KConfigParameter):
    """
    Abstraction of a linux kernel KConfig config option
    """
    # Configs start with "config" followed by the config name
    # Captures the prompt name if present
    start_regex = r'^config\s*(.+)*$'
    variable_type = None


class KConfigIf(KConfigParameter):
    """
    Abstraction of a linux kernel KConfig if option
    """
    # Ifs start with "if" followed by the if name
    # Captures the prompt name if present
    start_regex = r'if\s*(.+)*'
    end_regex = r'^endif.*$'


class KConfigTypes(Enum):
    choice = KConfigChoice
    menu = KConfigMenu
    menuconfig = KConfigMenuconfig
    config = KConfigConfig
    _if = KConfigIf


@class_logger
class KConfig:
    """
    Abstraction of a linux kernel KConfig collection

    All KConfig objects are meant to be used as a collection of KConfigParameter objects
    They share a common base path and architecture, and can be used to parse KConfig files
    """
    _source_re = r'^source\s+"(.+)"$'

    def __init__(self, file_path="Kconfig", base_path="/usr/src/linux", arch="x86", *args, **kwargs):
        """
        Creates a KConfig object
        """
        self.file_path = file_path
        self.base_path = base_path
        self.arch = arch

        self.sub_configs = dict()

        self.parse_config()

    def parse_config(self):
        """
        Parses a KConfig file
        """
        with open(f"{self.base_path}/{self.file_path}", 'r') as config_file:
            self.logger.info("Parsing config file: %s" % config_file.name)
            for line in config_file:
                self.parse_line(line)

    def _skip_line(self, config_line):
        """
        Checks if a line should be skipped
        """
        if config_line.startswith('#'):
            self.logger.log(5, "Skipping comment: %s" % config_line)
            return True
        elif config_line == '':
            self.logger.log(5, "Skipping empty line")
            return True
        else:
            return False

    def parse_line(self, config_line):
        """
        Parses a line from a KConfig file
        """
        # First remove the trailing spaces and newline
        config_line = config_line.rstrip()
        # Substitute the vars if possible
        config_line = self.substitute_vars(config_line)

        # Skip the line if it shouldn't be processed
        if self._skip_line(config_line):
            self.logger.log(5, "Skipping line: %s" % config_line)
            return

        # Check if the line is a source line and process it if so
        if re.search(self._source_re, config_line):
            source = re.search(self._source_re, config_line).group(1)
            self.logger.debug("Source line found: %s" % source)
            self.process_source(source)
            self.logger.info("Added source: %s" % source)
        # Attempt to process the line with the current config parameter if it's set
        elif hasattr(self, 'current_parameter') and self.current_parameter.process_line(config_line):
            self.logger.debug("Line processed using current parameter: %s" % self.current_parameter)
            return
        # Create a new config parameter using the line
        elif line_config := KConfigParameter(config_line):
            self.logger.info("Found config line: %s" % line_config)
            self.current_parameter = line_config

    def process_source(self, source):
        """
        Processes a source line
        """
        if source.endswith(".include"):
            self.logger.warning("Skipping include: %s" % source)
            return
        self.sub_configs[source] = KConfig(base_path=self.base_path, arch=self.arch, file_path=source)

    def substitute_vars(self, config_line):
        """
        Substitutes variables in a config line
        """
        if "$" not in config_line:
            return config_line

        if "$(SRCARCH)" in config_line:
            config_line = config_line.replace("$(SRCARCH)", self.arch)

        return config_line

    def __str__(self):
        """
        prints the contents of the KConfig object
        """
        out_str = f"Printing config for: {self.base_path}/{self.file_path}\n"
        if hasattr(self, 'current_parameter'):
            out_str += str(self.current_parameter)

        for config in self.sub_configs.values():
            out_str += str(config)
        return out_str


@class_logger
class KernelDict(dict):
    """
    Special dictionary for linux kernel config
    Meant to be used by LinuxKernelConfig

    Automatically tries to make a LinuxKernelConfigParameter defined by the name with the passed value when defined

    Exist to merge items as they are added, according to the mode
    Mostly just an updated __setitem__

    """
    def __init__(self, config_values={}, config_file='config.yaml', *args, **kwargs):
        """
        The config values should be a dict containing configuration, mostly to be used with expressions
        If config_file is set, it should be a path to a yaml file containing the config values
        """
        self.config_values = config_values
        self.config_file = config_file
        self.load_config()

    def __setitem__(self, key, value):
        """
        Tries to generate a new linux kernel config parameter based on the supplied information
        passes it to the update function which should handle merging
        """

        if config_parameter := self._gen_config_obj_from_dict(key, value):
            self.update_value(config_parameter)
        else:
            self.logger.warning("Failed to generate config parameter for: %s" % key)

    def load_config(self):
        """
        Loads the config values from the config file
        """
        from yaml import safe_load
        with open(self.config_file, 'r') as config_file:
            for key, value in safe_load(config_file).items():
                if key == 'templates':
                    self.load_yaml_template(value)
                else:
                    self.config_values[key] = value

    @handle_plural
    def load_yaml_template(self, template_file, template_dir='templates'):
        """
        Reads a yaml file containing kernel config values
        """
        template_file += '.yaml' if not template_file.endswith('.yaml') else ''
        from yaml import safe_load
        with open(f"{template_dir}/{template_file}", 'r') as yaml_file:
            for key, value in safe_load(yaml_file).items():
                self[key] = value

    def _gen_config_obj_from_dict(self, name, parameters):
        """
        Assists in the creation of a LinuxKernelConfigParameter object
        if config_values is just a string, sets value to that.

        If it's a dict, does advanced handling, based on how the yaml should be defined.

        NOTE: The standard processing method treats the value as a string, and the key as the name
        """
        kwargs = dict()
        kwargs['logger'] = self.logger
        kwargs['name'] = name

        if parameters is None:
            kwargs['defined'] = False
        elif isinstance(parameters, dict):
            self.logger.info("Advanced parameters detected for config: %s" % name)
            self.logger.debug("Parameters: %s" % parameters)
            kwargs['value'] = parameters['value']
            if 'description' in parameters:
                kwargs['description'] = parameters['description']
            if 'if' in parameters:
                # if there is an if expression, check it
                if True not in [self.check_expression(expression) for expression in parameters['if']]:
                    self.logger.warning("All tests failed for: %s" % parameters['if'])
                    return
        else:
            kwargs['value'] = str(parameters)

        return LinuxKernelConfigParameter(**kwargs)

    def update_value(self, value):
        """
        Updates a dict key to a valid LinuxKernelConfigParameter object
        """
        if not isinstance(value, LinuxKernelConfigParameter):
            raise ValueError("Value is not a LinuxKernelConfigParamter: %s" % value)

        if value.name in self:
            self.logger.warning("Key is already defined: %s" % self[value.name])

        super().__setitem__(value.name, value)

    def check_expression(self, expression):
        """
        Checks if an expression is true

        """
        self.logger.debug("Checking expression: %s" % expression)
        output = False
        if 'is' in expression:
            output = self._expression_is(expression)

        if 'in' in expression:
            output = self._expression_in(expression)

        return output

    def _expression_is(self, expression):
        """
        Checks that the 'value' is equal to the config parameter corresponding to the 'is' key
        """
        value = expression['value']
        config = self.config_values[expression['is']]
        self.logger.debug("Checking that '%s' is equal to: %s" % (value, config))
        return True if value == config else False

    def _expression_in(self, expression):
        """
        Checks that the 'value' is in the config parameter corresponding to the 'in' key
        """
        value = expression['value']
        config = self.config_values[expression['in']]
        self.logger.debug("Checking that '%s' is in list: %s" % (value, config))
        return True if value in config else False

    def __str__(self):
        return "".join([f"{str(parameter)}\n" for parameter in self.values()])


@class_logger
class LinuxKernelConfigParameter:
    """
    Abstraction of a linux kernel .config parameter
    """
    _invalid_name_chars = r'[^a-zA0-Z_0-9]'
    _basic_value_match = r'^(-?([0-9])+|[ynm])'
    _string_value_patch = r'^([a-zA-Z0-9/_.,-=\(\) ])*$'

    components = OrderedDict({'name': {'required': True},
                              'value': {'required': False},
                              'defined': {'required': False, 'default': True},
                              'description': {'required': False}})

    def __init__(self, *args, **kwargs):
        """
        Creates a LinuxKernelConfigParameter object
        based on the components defined in the components OrderedDict
        and the arguments passed in **kwargs
        """
        for component_name, specification in self.components.items():
            if component_name in kwargs:
                setattr(self, component_name, kwargs[component_name])
            elif 'default' in specification:
                setattr(self, component_name, specification['default'])
            elif specification['required']:
                raise ValueError(f"Missing required component {component_name}")

    def __setattr__(self, name, value):
        """
        When setting an attribute, checks if there is a _validate_{attribute_name} method,
        if so, checks if the value is valid before setting the attribute.

        If the checks pass, checks if there is a _set_{attribute_name} method, if so, calls
        that method to set the attribute.

        otherwise uses the default setattr method
        """
        if hasattr(self, f"_validate_{name}"):
            validator = getattr(self, f"_validate_{name}")
            if not validator(value):
                raise ValueError(f"Invalid value for {name}: {value}")

        if hasattr(self, f"_set_{name}"):
            getattr(self, f"_set_{name}")(value)
        else:
            super().__setattr__(name, value)

    def _set_name(self, name):
        """
        Sets the name, normalizes to a config paramter name, checks the name
        """
        name = name.upper()

        if not name.startswith('CONFIG_'):
            self.logger.info("Config name '%s' does not start with 'CONFIG_', appending" % name)
            name = 'CONFIG_' + name

        super().__setattr__('name', name)

    def _set_value(self, value):
        """
        Sets the value of the config parameter
        """
        if value is None:
            self.logger.warning("Value for '%s' is None, setting defined to False" % self.name)
            self.defined = False
        else:
            self.logger.debug("Value for '%s' is defined, setting defined to True" % self.name)
            self.defined = True

        super().__setattr__('value', value)

    def _validate_name(self, name):
        """Validates the characters in a kernel config parameter name"""
        return not re.search(self._invalid_name_chars, name)

    def _validate_value(self, value):
        """
        Validates the characters in a kernel config parameter value

        NOTE: This is a very basic check, it does not check if the value is valid for the parameter
        """
        if re.search(self._basic_value_match, str(value)):
            return True
        elif re.search(self._string_value_patch, value):
            return True
        else:
            return False

    def __str__(self):
        output_str = f"# {self.description}\n" if hasattr(self, 'description') else ""
        out_val = self.value if re.search(self._basic_value_match, str(self.value)) else f'"{self.value}"'
        output_str += f"{self.name}={out_val}" if self.defined else f"# {self.name} is not set"
        return output_str

