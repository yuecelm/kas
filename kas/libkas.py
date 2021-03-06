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
    This module contains the core implementation of kas.
"""

import re
import os
import sys
import logging
import tempfile
import asyncio
from subprocess import Popen, PIPE

__license__ = 'MIT'
__copyright__ = 'Copyright (c) Siemens AG, 2017'


class LogOutput:
    """
        Handles the log output of executed applications
    """
    def __init__(self, live):
        self.live = live
        self.stdout = []
        self.stderr = []

    def log_stdout(self, line):
        """
            This method is called when a line over stdout is received.
        """
        if self.live:
            logging.info(line.strip())
        self.stdout.append(line)

    def log_stderr(self, line):
        """
            This method is called when a line over stderr is received.
        """
        if self.live:
            logging.error(line.strip())
        self.stderr.append(line)


@asyncio.coroutine
def _read_stream(stream, callback):
    """
        This asynchronious method reads from the output stream of the
        application and transfers each line to the callback function.
    """
    while True:
        line = yield from stream.readline()
        try:
            line = line.decode('utf-8')
        except UnicodeDecodeError as err:
            logging.warning('Could not decode line from stream, ignore it: %s',
                            err)
        if line:
            callback(line)
        else:
            break


@asyncio.coroutine
def _stream_subprocess(cmd, cwd, env, shell, stdout_cb, stderr_cb):
    """
        This function starts the subprocess, sets up the output stream
        handlers and waits until the process has existed
    """
    # pylint: disable=too-many-arguments

    if shell:
        process = yield from asyncio.create_subprocess_shell(
            cmd,
            env=env,
            cwd=cwd,
            universal_newlines=True,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    else:
        process = yield from asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

    yield from asyncio.wait([
        _read_stream(process.stdout, stdout_cb),
        _read_stream(process.stderr, stderr_cb)
    ])
    ret = yield from process.wait()
    return ret


def run_cmd(cmd, cwd, env=None, fail=True, shell=False, liveupdate=True):
    """
        Starts a command.
    """
    # pylint: disable=too-many-arguments

    env = env or {}
    retc = 0
    cmdstr = cmd
    if not shell:
        cmdstr = ' '.join(cmd)
    logging.info('%s$ %s', cwd, cmdstr)

    logo = LogOutput(liveupdate)
    if asyncio.get_event_loop().is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    else:
        loop = asyncio.get_event_loop()

    retc = loop.run_until_complete(
        _stream_subprocess(cmd, cwd, env, shell,
                           logo.log_stdout, logo.log_stderr))
    loop.close()

    if retc and fail:
        msg = 'Command "{cwd}$ {cmd}" failed\n'.format(cwd=cwd, cmd=cmdstr)
        for line in logo.stderr:
            msg += line
        logging.error(msg)
        sys.exit(retc)

    return (retc, ''.join(logo.stdout))


def find_program(paths, name):
    """
        Find a file within the paths array and returns its path.
    """
    for path in paths.split(os.pathsep):
        prg = os.path.join(path, name)
        if os.path.isfile(prg):
            return prg
    return None


def repo_fetch(config, repo):
    """
        Fetches the repository to the kas_work_dir.
    """
    if repo.git_operation_disabled:
        return

    if not os.path.exists(repo.path):
        os.makedirs(os.path.dirname(repo.path), exist_ok=True)
        gitsrcdir = os.path.join(config.get_repo_ref_dir() or '',
                                 repo.qualified_name)
        logging.debug('Looking for repo ref dir in %s', gitsrcdir)
        if config.get_repo_ref_dir() and os.path.exists(gitsrcdir):
            run_cmd(['/usr/bin/git',
                     'clone',
                     '--reference', gitsrcdir,
                     repo.url, repo.path],
                    env=config.environ,
                    cwd=config.kas_work_dir)
        else:
            run_cmd(['/usr/bin/git', 'clone', '-q', repo.url,
                     repo.path],
                    env=config.environ,
                    cwd=config.kas_work_dir)
        return

    # Does refspec in the current repository?
    (retc, output) = run_cmd(['/usr/bin/git', 'cat-file',
                              '-t', repo.refspec], env=config.environ,
                             cwd=repo.path, fail=False)
    if retc == 0:
        return

    # No it is missing, try to fetch
    (retc, output) = run_cmd(['/usr/bin/git', 'fetch', '--all'],
                             env=config.environ,
                             cwd=repo.path, fail=False)
    if retc:
        logging.warning('Could not update repository %s: %s',
                        repo.name, output)


def repo_checkout(config, repo):
    """
        Checks out the correct revision of the repo.
    """
    if repo.git_operation_disabled:
        return

    # Check if repos is dirty
    (_, output) = run_cmd(['/usr/bin/git', 'diff', '--shortstat'],
                          env=config.environ, cwd=repo.path,
                          fail=False)
    if len(output):
        logging.warning('Repo %s is dirty. no checkout', repo.name)
        return

    # Check if current HEAD is what in the config file is defined.
    (_, output) = run_cmd(['/usr/bin/git', 'rev-parse',
                           '--verify', 'HEAD'],
                          env=config.environ, cwd=repo.path)

    if output.strip() == repo.refspec:
        logging.info('Repo %s has already checkout out correct '
                     'refspec. nothing to do', repo.name)
        return

    run_cmd(['/usr/bin/git', 'checkout', '-q',
             '{refspec}'.format(refspec=repo.refspec)],
            cwd=repo.path)


def get_build_environ(config, build_dir):
    """
        Create the build environment variables.
    """
    # pylint: disable=too-many-locals
    # nasty side effect function: running oe/isar-init-build-env also
    # creates the conf directory

    permutations = \
        [(repo, script) for repo in config.get_repos()
         for script in ['oe-init-build-env', 'isar-init-build-env']]
    for (repo, script) in permutations:
        if os.path.exists(repo.path + '/' + script):
            init_path = repo.path
            init_script = script
            break
    else:
        logging.error('Did not find any init-build-env script')
        sys.exit(1)

    get_bb_env_file = tempfile.mktemp()
    with open(get_bb_env_file, 'w') as fds:
        script = """#!/bin/bash
        source %s $1 > /dev/null 2>&1
        env
        """ % init_script
        fds.write(script)
    os.chmod(get_bb_env_file, 0o775)

    env = {}
    env['PATH'] = '/bin:/usr/bin'

    (_, output) = run_cmd([get_bb_env_file, build_dir],
                          cwd=init_path, env=env, liveupdate=False)

    os.remove(get_bb_env_file)

    env = {}
    for line in output.splitlines():
        try:
            (key, val) = line.split('=', 1)
            env[key] = val
        except ValueError:
            pass

    env_vars = ['SSTATE_DIR', 'DL_DIR', 'TMPDIR']
    if 'BB_ENV_EXTRAWHITE' in env:
        extra_white = env['BB_ENV_EXTRAWHITE'] + ' '.join(env_vars)
        env.update({'BB_ENV_EXTRAWHITE': extra_white})

    env_vars.extend(['SSH_AGENT_PID', 'SSH_AUTH_SOCK',
                     'SHELL', 'TERM'])

    for env_var in env_vars:
        if env_var in os.environ:
            env[env_var] = os.environ[env_var]

    return env


def ssh_add_key(env, key):
    """
        Add ssh key to the ssh-agent
    """
    process = Popen(['/usr/bin/ssh-add', '-'], stdin=PIPE, stdout=None,
                    stderr=PIPE, env=env)
    (_, error) = process.communicate(input=str.encode(key))
    if process.returncode and error:
        logging.error('failed to add ssh key: %s', error)


def ssh_cleanup_agent(config):
    """
        Removes the identities and stop the ssh-agent instance
    """
    # remove the identities
    process = Popen(['/usr/bin/ssh-add', '-D'], env=config.environ)
    process.wait()
    if process.returncode != 0:
        logging.error('failed to delete SSH identities')

    # stop the ssh-agent
    process = Popen(['/usr/bin/ssh-agent', '-k'], env=config.environ)
    process.wait()
    if process.returncode != 0:
        logging.error('failed to stop SSH agent')


def ssh_setup_agent(config, envkeys=None):
    """
        Starts the ssh-agent
    """
    envkeys = envkeys or ['SSH_PRIVATE_KEY']
    output = os.popen('/usr/bin/ssh-agent -s').readlines()
    for line in output:
        matches = re.search(r"(\S+)\=(\S+)\;", line)
        if matches:
            config.environ[matches.group(1)] = matches.group(2)

    for envkey in envkeys:
        key = os.environ.get(envkey)
        if key:
            ssh_add_key(config.environ, key)
        else:
            logging.warning('%s is missing', envkey)


def ssh_no_host_key_check(_):
    """
        Disables ssh host key check
    """
    home = os.path.expanduser('~')
    if not os.path.exists(home + '/.ssh'):
        os.mkdir(home + '/.ssh')
    with open(home + '/.ssh/config', 'w') as fds:
        fds.write('Host *\n\tStrictHostKeyChecking no\n\n')
