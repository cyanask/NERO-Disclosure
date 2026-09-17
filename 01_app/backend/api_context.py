"""Explicit dependencies shared by the workflow route modules.

Route modules receive this instead of closing over create_app locals, so the
collaborators a group of endpoints uses are visible in one place.
"""


class WorkflowContext:
    """Roots, seeds, storage, security, runtime and the creation-time mode flag."""

    def __init__(self,root,directory,seeds,store,security,runtime=None,legacy_test_mode=False):
        self.root=root
        self.directory=directory
        self.seeds=seeds
        self.store=store
        self.security=security
        self.runtime=runtime
        self.legacy_test_mode=legacy_test_mode
