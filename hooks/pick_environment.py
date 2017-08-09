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
from tank import TemplatePath

class PickEnvironment(Hook):

    def execute(self, context, **kwargs):
        """
        The default implementation assumes there are three environments, called shot, asset
        and project, and switches to these based on entity type.

        DD implementation includes Sequence and Step
        """



        if context.project is None:
            # our context is completely empty!
            # don't know how to handle this case.
            return "site"

        if context.entity is None:
            # we have a project but not an entity
            return "project"

        if context.entity and context.step is None:
            # we have an entity but no step!
            if context.entity["type"] == "Project":
                return "project"
            if context.entity["type"] == "Sequence":
                return "sequence"
            if context.entity["type"] == "Shot":
                return "shot"
            if context.entity["type"] == "Step":
                return "shot"
            if context.entity["type"] == "Asset":
                return "asset"
        if context.entity and context.step:
            # we have a step and an entity
            if context.entity["type"] == "Project":
                return "project_stp"
            if context.entity["type"] == "Sequence":
                return "sequence_step"
            if context.entity["type"] == "Shot":
                return "shot_step"
            if context.entity["type"] == "Step":
                return "shot_step"
            if context.entity["type"] == "Asset":
                return "asset_step"

        return None
