
# Copyright (C) 2013 - 2016 - Oscar Campos <oscar.campos@member.fsf.org>
# This program is Free Software see LICENSE file for details

import os
import sys
import time
import socket
import logging

import sublime

from .worker_ng import Worker
from .remoteworker import RemoteChecker
from .builder.python_builder import AnacondaSetPythonBuilder
from .helpers import get_settings, active_view, project_name, create_subprocess

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))
logger.setLevel(logging.INFO)


class LocalProcesser(object):
    """Starts a new local instance of the JsonServer
    """

    def __init__(self):
        self.last_error = {}
        self._process = None

    @property
    def script_file(self):
        """Return back the script file to execute
        """

        return os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'anaconda_server', 'jsonserver.py'
        )

    def is_healthy(self):
        """Checks if the server process is healthy
        """

        if get_settings(active_view(), 'jsonserver_debug', False):
            return True

        if self._process.poll() is not None:
            self.last_error = {
                'error': 'the jsonserver process is terminated',
                'recommendation': 'check your configuration'
            }
            return False

        return True

    def start(self, worker):
        """Create the subprocess for the anaconda json server process
        """

        view = active_view()
        self.project_name = project_name()
        args, kwargs = self._prepare_arguments(view, worker)
        self._process = create_subprocess(args, **kwargs)
        if self._process is None:
            # we can't spawn a new process for jsonserver. Wrong config?
            example = '/usr/bin/python'
            if os.name == 'nt':
                example = 'C:\\Python27\\python.exe'

            self.last_error = {
                'error': (
                    'Anaconda can not spawn a new process with your current '
                    'configured python interpreter ({})'.format(args[0])
                ),
                'recommendation': (
                    'Make sure your interpeter is a valid binary and is in '
                    'your PATH or use an absolute route to it, '
                    'for example: {}'.format(example)
                )
            }
            return False

        return True

    def _get_extra_paths(self, view):
        """Return back a list of extra paths to be added to jedi
        """

        extra_paths = get_settings(view, 'extra_paths', [])
        paths = [os.path.expanduser(p) for p in extra_paths]

        try:
            paths.extend(sublime.active_window().folders())
        except AttributeError:
            logger.warning(
                'Your `extra_paths` configuration is a string but we are '
                'expecting a list of string.'
            )
            paths = paths.split(',')
            paths.extend(sublime.active_window().folders())

        return paths

    def _get_python_interpreter(self, view):
        """Return back the configured python interpreter
        """

        try:
            python = os.path.expanduser(
                get_settings(view, 'python_interpreter', 'python'))
            if '$VIRTUAL_ENV' in python:
                if 'VIRTUAL_ENV' in os.environ:
                    python = python.replace(
                        '$VIRTUAL_ENV', os.environ.get('VIRTUAL_ENV'))
                else:
                    logging.warning(
                        'WARNING: your anaconda configured python interpeter '
                        'is {} but there is no $VIRTUAL_ENV key in your '
                        'environment, falling back to `python`'.format(
                            get_settings(view, 'python_interpreter', 'python')
                        )
                    )
        except:
            python = 'python'
        finally:
            return python

    def _sanitize_paths(self, paths):
        """Remove non existent directories from paths due ST3 caching bugs
        """

        for path in paths[:]:
            if not os.path.exists(path):
                paths.remove(path)

    def _prepare_arguments(self, view, worker):
        """Prepare subprocess arguments
        """

        paths = self._get_extra_paths(view)
        python = self._get_python_interpreter(view)

        args = [python, '-B', self.script_file, '-p', self.project_name]
        args.append(str(worker.port))
        if len(paths) > 0:
            self._sanitize_paths(paths)
            args.extend(['-e', ','.join(paths)])

        args.extend([str(os.getpid())])

        kwargs = {}
        folders = sublime.active_window().folders()
        if len(folders) > 0 and os.path.exists(folders[0]):
            kwargs['cwd'] = folders[0]

        return args, kwargs


class LocalChecker(RemoteChecker):
    """Implements generic checks for local JsonServer
    """

    def check(self, worker):
        """Perform required checks to conclude is it's safe to operate
        """

        # if last_error is not empty just return False
        if not not self.last_error:
            return False

        if not worker.processer.is_healthy():
            self.last_error = worker.processer.last_error
            return False

        timeout = 0
        while not self._status(worker, 0.05):
            if timeout >= 200:
                return False
            time.sleep(0.1)
            timeout += 1

        return True

    def renew_port(self):
        """Force port renewal for the jsonserver
        """

        self._remote_addr = None

    def _extract_addr(self):
        """Extract the addr as a tuple (hostaddr, port)
        """

        host, port = 'localhost', None
        view = active_view()
        if get_settings(view, 'jsonserver_debug', False):
            port = get_settings(view, 'jsonserver_debuug_port', 9999)
            self._remote_addr = (host, port)
            return

        s = socket.socket()
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        self._remote_addr = (host, port)


class LocalWorker(Worker):
    """
    This class implements a local worker, it's start a local instance
    of the anaconda's full JsonServer, this is the most common use case
    """

    def __init__(self):

        self.reconnecting = False
        super(LocalWorker, self).__init__(LocalChecker(), LocalProcesser())

    def start(self):
        """Start the worker and it's services
        """

        self._update_python_builder()
        if self.reconnecting:
            self.checker.renew_port()

        super(LocalWorker, self).start()

    def _update_python_builder(self):
        view = active_view()
        p_data = sublime.active_window().project_data()
        if p_data is not None:
            python_interpeter = self.processer._get_python_interpreter(view)
            AnacondaSetPythonBuilder().update_interpreter_build_system(
                python_interpeter
            )
