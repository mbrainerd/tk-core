# built-in packages
import pstats
import cProfile


class CProfileMethodRunner(object):
    """
    How to use:

    from sgtk import CProfileMethodRunner

    @CProfileMethodRunner.start_profiler(save_stats=False)
    def init_app(self):
        entry_point_function_contents

    @CProfileMethodRunner.stop_profiler(profiling_output="/dd/home/gverma/work/profiling_output_tk-nuke-write.pstat",
                                        save_stats=True)
    def destroy_app(self):
        exit_point_function_contents
    """

    profiler = None

    def __init__(self, profiling_output, init_new_profiler, stop_profiler, save_stats):
        """
        CProfileMethodRunner Decorator class to output profiling stats

        :param profiling_output: File to write the output to.
        :param init_new_profiler: Initialize the class instance of the profiler with a new cProfile instance.
        :param stop_profiler: Disable/Dump the stats of the class instance of the profiler, and make it None again.
        :param save_stats: Whether to dump out unprocessed stats or not.
        """

        self.profiling_output = profiling_output
        self.init_new_profiler = init_new_profiler
        self.stop_profiler = stop_profiler
        self.save_stats = save_stats
        # to save ourselves from this! the classmethod should have some *args
        # otherwise the __call__ function doesn't get "func" as the argument
        # self.func = func

    @classmethod
    def start_profiler(cls, save_stats):
        """
        Start the profiler instance of the class
        """
        return cls(profiling_output=None, init_new_profiler=True, stop_profiler=False, save_stats=save_stats)

    @classmethod
    def stop_profiler(cls, profiling_output, save_stats):
        """
        Stop the profiler instance of the class
        """
        return cls(profiling_output=profiling_output,
                   init_new_profiler=False, stop_profiler=True, save_stats=save_stats)

    def __call__(self, func):
        """
        Call function runs the wrapped function to perform the decoration.
        """
        def wrapped_f(*args, **kwargs):
            try:
                # init the class profiler
                if not CProfileMethodRunner.profiler and self.init_new_profiler:
                    CProfileMethodRunner.profiler = cProfile.Profile()
                    print "Starting CProfiler on %s.%s..." % (func.__module__, func.__name__)
                    CProfileMethodRunner.profiler.enable()
                elif self.init_new_profiler:
                    print "CProfile is already running!"
                # execute the actual function
                result = func(*args, **kwargs)
                return result
            finally:
                if self.stop_profiler:
                    if self.save_stats:
                        CProfileMethodRunner.profiler.dump_stats(self.profiling_output)
                    else:
                        with open(self.profiling_output, 'w+') as stream:
                            stats = pstats.Stats(CProfileMethodRunner.profiler, stream=stream)
                            stats.strip_dirs()
                            stats.sort_stats(-1)
                            stats.print_stats()
                    # disable the profiler and clean for the next session
                    if CProfileMethodRunner.profiler and self.stop_profiler:
                        CProfileMethodRunner.profiler.disable()
                        del CProfileMethodRunner.profiler
                        CProfileMethodRunner.profiler = None
                        print "Ending CProfiler on %s.%s..." % (func.__module__, func.__name__)

        return wrapped_f


class CProfileRunner(object):
    """
    How to use:

    from sgtk import CProfileRunner

    @CProfileRunner(profiling_output="path_to_pstat_or_resolved_stat_file_if_save_stats_is_false", save_stats=True)
    def start_toolkit():
        function_contents
    """

    def __init__(self, profiling_output, save_stats=False):
        """
        CProfileRunner Decorator class to output profiling stats

        :param profiling_output: File to write the output to.
        :param save_stats: Whether to dump out unprocessed stats or not.
        """

        self.profiling_output = profiling_output
        self.save_stats = save_stats

    def __call__(self, func):
        """
        Call function runs the wrapped function to perform the decoration.
        """
        def wrapped_f(*args, **kwargs):
            profiler = cProfile.Profile()
            try:
                print "Starting CProfiler on %s.%s..." % (func.__module__, func.__name__)
                profiler.enable()
                # execute the actual function
                result = func(*args, **kwargs)
                profiler.disable()
                print "Ending CProfiler on %s.%s..." % (func.__module__, func.__name__)
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