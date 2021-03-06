# kas - setup tool for bitbake based projects
#
# Copyright (c) Siemens AG, 2017
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
    This module contains a kas plugin that opens a shell within the kas
    environment
"""

import subprocess
from kas.config import load_config
from kas.libcmds import (Macro, Command, SetupProxy, SetupEnviron, SetupHome)

__license__ = 'MIT'
__copyright__ = 'Copyright (c) Siemens AG, 2017'


class Shell:
    """
        Implements a kas plugin that opens a shell within the kas environment.
    """

    def __init__(self, parser):
        sh_prs = parser.add_parser('shell')

        sh_prs.add_argument('config',
                            help='Config file')
        sh_prs.add_argument('--target',
                            help='Select target to build',
                            default='core-image-minimal')
        sh_prs.add_argument('--skip',
                            help='Skip build steps',
                            default=[])
        sh_prs.add_argument('-c', '--command',
                            help='Run command',
                            default='')

    def run(self, args):
        """
            Runs this kas plugin
        """
        # pylint: disable= no-self-use

        if args.cmd != 'shell':
            return False

        cfg = load_config(args.config, args.target)

        macro = Macro()

        macro.add(SetupProxy())
        macro.add(SetupEnviron())
        macro.add(SetupHome())
        macro.add(ShellCommand(args.command))

        macro.run(cfg, args.skip)

        return True


class ShellCommand(Command):
    """
        This class implements the command that starts a shell.
    """

    def __init__(self, cmd):
        super().__init__()
        self.cmd = []
        if cmd:
            self.cmd = cmd

    def __str__(self):
        return 'shell'

    def execute(self, config):
        cmd = [config.environ.get('SHELL', '/bin/sh')]
        if self.cmd:
            cmd.append('-c')
            cmd.append(self.cmd)
        subprocess.call(cmd, env=config.environ,
                        cwd=config.build_dir)
