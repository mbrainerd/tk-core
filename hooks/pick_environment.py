# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Hook which chooses an environment file to use based on the current context.
"""

from tank import Hook

class PickEnvironment(Hook):

    def execute(self, context, **kwargs):
        """
        The default implementation assumes there are three environments, called shot, asset
        and project, and switches to these based on entity type.

        DD implementation includes additional Project/Sequence Step environments as well as
        Sequence/Shot Asset environments
        """
        env_name = "site"
        if context.project:
            env_name = "project"
            if context.entity:
                env_name = context.entity["type"].lower()

                if context.entity["type"] == "Asset":
                    if "Shot" in context.parent_entities:
                        env_name = "shot_" + env_name
                    elif "Sequence" in context.parent_entities:
                        env_name = "sequence_" + env_name

            if context.step:
                env_name += "_step"

        return env_name
