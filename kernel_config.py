#!/usr/bin/env python3
"""
Used to create kernel configuration files for specific hardware configurations
"""

__version__ = "0.0.3"

from zen_custom import class_logger, handle_plural

from collections import OrderedDict

import re


@class_logger
class KConfig:
    """
    Abstraction of a linux kernel KConfig collection

    All KConfig objects are meant to be used as a collection of KConfigParameter objects
    They share a common base path and architecture, and can be used to parse KConfig files
    """
    _source_regex = r'source\s+\"(.*)\"'
    _help_exits = ['select', 'config', 'menu', 'endmenu', 'endchoice', 'endif']
    arch = "x86"
    base_path = "/usr/src/linux"

    def __init__(self, file_path="Kconfig", menu=None, base_path=None, arch=None, *args, **kwargs):
        """
        Creates a KConfig object
        """
        if base_path:
            self.logger.info("Overriding attribute: base_path: %s -> %s" % (self.base_path, base_path))
            self.base_path = base_path
        if arch:
            self.logger.info("Overriding attribute: arch: %s -> %s" % (self.arch, arch))
            self.arch = arch

        self.in_menu = menu
        if menu:
            self.logger.info("Initializing KConfig object with menu: %s" % menu)

        self.config_types = ['config', 'menu', 'sub_configs']
        for config_type in self.config_types:
            setattr(self, config_type, dict())

        self.help_mode = False

        self.file_path = file_path
        self.parse_config()

    #    for thread, exception in self._threads:
    #        thread.join()
    #        while not exception.empty():
    #            self.logger.error("Exception in thread: %s" % exception.get())

    # @threaded
    def parse_config(self):
        """
        Parses a KConfig file
        """
        with open(f"{self.base_path}/{self.file_path}", 'r') as config_file:
            self.logger.info("Parsing config file: %s" % config_file.name)
            for line in config_file:
                self.parse_line(line)

    def parse_line(self, config_line):
        """
        Parses a line from a KConfig file
        """
        config_line = config_line.strip()
        config_line = self.substitute_vars(config_line)

        # Checks if the line is a comment or empty, and skips it if so
        if config_line.startswith('#'):
            self.logger.debug("Skipping comment: %s" % config_line)
            return
        elif config_line == '':
            self.logger.debug("Skipping empty line")
            return

        if self.help_mode:
            # Checks if the current mode dict has a help key, initialized it to an empty string if not
            if 'help' not in getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]:
                getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['help'] = ''
            # If another defintion is found, exit help mode, otherwise append the line to the help string
            if True in [config_line.startswith(config_type) for config_type in self._help_exits]:
                self.help_mode = False
            else:
                self.logger.debug("Appending help line: %s" % config_line)
                getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['help'] += config_line
        # if help mode hasn't been exited, skip the rest of the parsing
        if self.help_mode:
            return

        if config_line == 'endmenu':
            self.logger.info("Found endmenu line")
            self.mode = None
            self.in_menu = None
        elif config_line == 'help':
            self.logger.info("Found help line")
            self.help_mode = True
        elif re.search(self._source_regex, config_line):
            # Handles source lines, which are just other config files
            # Uses the base path and the content between the quotes
            source_path = config_line.split()[1].strip('\"')
            self.logger.info("Found source line: %s" % source_path)
            if source_path.endswith(".include"):
                self.logger.warning("Skipping include file: %s" % source_path)
                return
            if self.in_menu:
                self.sub_configs[source_path] = KConfig(file_path=source_path, menu=self.in_menu, logger=self.logger)
            else:
                self.sub_configs[source_path] = KConfig(file_path=source_path, logger=self.logger)
        elif config_line.startswith('config '):
            self.current_config = config_line.split()[1]
            if self.current_config not in self.config:
                self.config[self.current_config] = dict()
            else:
                self.logger.warning("Config already exists: %s" % self.current_config)
            self.logger.info("Found config line: %s" % config_line)
            self.mode = 'config'
        elif config_line.startswith('menu '):
            self.in_menu = config_line.split()[1]
        elif config_line.startswith('menuconfig '):
            if '"' in config_line:
                self.current_menu = config_line.split('"')[1]
            else:
                self.current_menu = config_line.split()[1]
            if self.current_menu not in self.menu:
                self.menu[self.current_menu] = dict()
            else:
                self.logger.warning("Menu already exists: %s" % self.current_menu)
            self.logger.info("Found menu line: %s" % config_line)
            self.mode = 'menu'
        elif config_line.startswith('select '):
            select = config_line.split()[1]
            current_mode = getattr(self, 'current_' + self.mode)
            if 'select' not in getattr(self, self.mode)[current_mode]:
                getattr(self, self.mode)[current_mode]['select'] = dict()
            self.logger.info("[%s] Found %s select line: %s" % (self.mode, current_mode, config_line))
            self.process_select(select)
        elif config_line.startswith('default '):
            default = config_line.split()[1:]
            self.logger.info("Found default line: %s" % config_line)
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['default'] = default
        elif config_line == 'bool':
            self.logger.info("Found basic bool line")
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['type'] = 'bool'
        elif config_line.startswith('bool '):
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['type'] = 'bool'
            prompt = config_line.split('"')[1]
            self.logger.info("Found bool line with prompt: %s" % config_line)
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['prompt'] = prompt.strip('\"')
        elif config_line.startswith('def_bool '):
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['type'] = 'bool'
            default = config_line.split()[1:]
            self.logger.info("Found bool line with default: %s" % config_line)
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['default'] = default
        elif config_line == 'string':
            self.logger.info("Found basic string line")
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['type'] = 'string'
        elif config_line.startswith('string '):
            prompt = config_line.split('"')[1]
            self.logger.info("Found string line with prompt: %s" % config_line)
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['prompt'] = prompt.strip('\"')
        elif config_line == 'int':
            self.logger.info("Found basic int line")
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['type'] = 'int'
        else:
            self.logger.warning("Unknown line type: %s" % config_line)

    def process_select(self, config_line):
        """
        Processes a select line
        """
        if 'if' in config_line:
            self.logger.info("Found select if line: %s" % config_line)
            select, if_statement = config_line.split('if')
            self.logger.warning("Select if statement not implemented: %s" % if_statement)
        else:
            self.logger.info("Found basic select line: %s" % config_line)
            getattr(self, self.mode)[getattr(self, 'current_' + self.mode)]['select'][config_line] = dict()

    def substitute_vars(self, config_line):
        """
        Substitutes variables in a config line
        """
        if "$" not in config_line:
            return config_line

        if "$(SRCARCH)" in config_line:
            config_line = config_line.replace("$(SRCARCH)", self.arch)

        return config_line

    def print_all_sub_configs(self):
        """
        Prints all sub configs, recursively
        """
        for name, config in self.sub_configs.items():
            print(f"Sub Config: {name}")
            config.print_all_sub_configs()

    def print_all_configs(self):
        """
        Prints all configs, including sub configs
        """
        for config_type in self.config_types:
            if config_type == 'sub_configs':
                self.logger.debug("Skipping sub_configs")
                continue
            print(f"Printing {config_type}:")
            for name, config in getattr(self, config_type).items():
                print(f"{name}: {config}")

        for name, config in self.sub_configs.items():
            print(f"Sub Config: {name}")
            config.print_all_configs()


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

