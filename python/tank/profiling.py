# built-in packages
import os
import pstats
import cProfile

# sgtk packages
from .util import LocalFileStorageManager
from .platform import get_logger

logger = get_logger(__name__)


class CProfileMethodRunner(object):
    """
    Notes::

    Creates a new profiler object for each and every different module the method is run on... possible conflicts.
    If the stop_profiler classmethod is never called since SGTK import modules with custom names, and it might happen
    that the stop_profiler doesn't accept the profiler to stop since the module name is not the same anymore.

    Usage::

    from sgtk.profiling import CProfileMethodRunner

    @CProfileMethodRunner.start_profiler(profiling_identifier="tk-nuke-writenode")
    def init_app(self):
        entry_point_function_contents

    @CProfileMethodRunner.stop_profiler(profiling_identifier="tk-nuke-writenode")
    def destroy_app(self):
        exit_point_function_contents

    The above profiler will output the stats in `$SHOTGUN_HOME/logs/profiling_output_tk-nuke-writenode.pstat`.
    """

    profiler_mapping = dict()

    def __init__(self, profiling_identifier, init_new_profiler, stop_profiler, save_stats=True):
        """
        CProfileMethodRunner Decorator class to output profiling stats.

        On the basis of profiling_identifier, it writes out stat files,
        to $SHOTGUN_HOME/logs/profiling_output_<profiling_identifier>.pstat.

        If, profiling_identifier is None, it writes out stat files,
        to $SHOTGUN_HOME/logs/profiling_output_unnamed.pstat.


        :param profiling_identifier: Identifier of the file that we are writing the output.
        :param init_new_profiler: Initialize the class instance of the profiler with a new cProfile instance.
        :param stop_profiler: Disable/Dump the stats of the class instance of the profiler, and make it None again.
        :param save_stats: Whether to dump out a pstat file or not, by default it writes out pstat file.
        """

        if profiling_identifier:
            self._profiling_identifier = profiling_identifier
        else:
            self._profiling_identifier = "unnamed"

        if save_stats:
            self._file_extension = "pstat"
        else:
            self._file_extension = "stats"

        output_directory = LocalFileStorageManager.get_global_root(LocalFileStorageManager.LOGGING)
        output_filename = "profiling_output_%s.%s" % (self._profiling_identifier, self._file_extension)
        profiling_output = os.path.join(output_directory, output_filename)

        self.profiling_output = profiling_output
        self.init_new_profiler = init_new_profiler
        self.stop_profiler = stop_profiler
        self.save_stats = save_stats

        # to save ourselves from this! the classmethod should have some *args
        # otherwise the __call__ function doesn't get "func" as the argument
        # self.func = func

    @classmethod
    def start_profiler(cls, profiling_identifier):
        """
        Start the profiler instance of the class
        """
        return cls(profiling_identifier=profiling_identifier, init_new_profiler=True, stop_profiler=False)

    @classmethod
    def stop_profiler(cls, profiling_identifier, save_stats=True):
        """
        Stop the profiler instance of the class
        """
        return cls(profiling_identifier=profiling_identifier,
                   init_new_profiler=False, stop_profiler=True, save_stats=save_stats)

    def __call__(self, func):
        """
        Call function runs the wrapped function to perform the decoration.
        """
        def wrapped_f(*args, **kwargs):
            func_module = func.__module__
            func_name = func.__name__
            try:
                # init the class profiler
                if func_module not in CProfileMethodRunner.profiler_mapping and self.init_new_profiler:
                    CProfileMethodRunner.profiler_mapping[func_module] = cProfile.Profile()
                    profiler = CProfileMethodRunner.profiler_mapping[func_module]
                    logger.info("Starting CProfiler on %s.%s.%s..." % (self._profiling_identifier, func_module, func_name))
                    profiler.enable()
                elif self.init_new_profiler:
                    logger.info("CProfile is already running for %s.%s!" % (self._profiling_identifier, func_module))
                # execute the actual function
                result = func(*args, **kwargs)
                return result
            finally:
                if func_module in CProfileMethodRunner.profiler_mapping and self.stop_profiler:
                    profiler = CProfileMethodRunner.profiler_mapping.pop(func_module)
                    if self.save_stats:
                        profiler.dump_stats(self.profiling_output)
                    else:
                        with open(self.profiling_output, 'w+') as stream:
                            stats = pstats.Stats(profiler, stream=stream)
                            stats.strip_dirs()
                            stats.sort_stats(-1)
                            stats.print_stats()

                    # disable the profiler and clean for the next session
                    profiler.disable()
                    del profiler
                    logger.info("Ending CProfiler on %s.%s.%s..." % (self._profiling_identifier, func_module, func_name))
                    logger.info("Writing: %s" % self.profiling_output)

        return wrapped_f


class CProfileRunner(object):
    """
    Usage::

    from sgtk.profiling import CProfileRunner

    @CProfileRunner(profiling_identifier="tk-nuke-writenode")
    def start_toolkit():
        function_contents

    The above profiler will output the stats in `$SHOTGUN_HOME/logs/profiling_output_tk-nuke-writenode.pstat`.
    """

    def __init__(self, profiling_identifier, save_stats=True):
        """
        CProfileRunner Decorator class to output profiling stats

        On the basis of profiling_identifier, it writes out stat files,
        to $SHOTGUN_HOME/logs/profiling_output_<profiling_identifier>.pstat.

        If, profiling_identifier is None, it writes out stat files,
        to $SHOTGUN_HOME/logs/profiling_output_unnamed.pstat.

        :param profiling_identifier: Identifier of the file that we are writing the output.
        :param save_stats: Whether to dump out a pstat file or not, by default it writes out pstat file.
        """

        if profiling_identifier:
            self._profiling_identifier = profiling_identifier
        else:
            self._profiling_identifier = "unnamed"

        if save_stats:
            self._file_extension = "pstat"
        else:
            self._file_extension = "stats"

        output_directory = LocalFileStorageManager.get_global_root(LocalFileStorageManager.LOGGING)
        output_filename = "profiling_output_%s.%s" % (self._profiling_identifier, self._file_extension)
        profiling_output = os.path.join(output_directory, output_filename)

        self.profiling_output = profiling_output
        self.save_stats = save_stats

    def __call__(self, func):
        """
        Call function runs the wrapped function to perform the decoration.
        """
        def wrapped_f(*args, **kwargs):
            func_module = func.__module__
            func_name = func.__name__
            profiler = cProfile.Profile()
            try:
                logger.info("Starting CProfiler on %s.%s.%s..." % (self._profiling_identifier, func_module, func_name))
                profiler.enable()
                # execute the actual function
                result = func(*args, **kwargs)
                profiler.disable()
                logger.info("Ending CProfiler on %s.%s.%s..." % (self._profiling_identifier, func_module, func_name))
                logger.info("Writing: %s" % self.profiling_output)
                return result
            finally:
                if self.save_stats:
                    profiler.dump_stats(self.profiling_output)
                else:
                    with open(self.profiling_output, 'w+') as stream:
                        stats = pstats.Stats(profiler, stream=stream)
                        stats.strip_dirs()
                        stats.sort_stats(-1)
                        stats.print_stats()
        return wrapped_f