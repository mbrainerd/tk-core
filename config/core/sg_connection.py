from sgtk import Hook
import os

class ShotgunConnection(Hook):

    def execute(self, config_data, user, cfg_path, **kwargs):
        """
        Allows for post processing of Shotgun connection data prior to connection
        """
        # expand host environment variable
        config_data['host'] = os.path.expandvars(config_data['host'])

        return config_data
