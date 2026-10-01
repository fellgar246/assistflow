"""Application-only approval grant.

The agent loop never constructs this object. Tool arguments cannot become one.
"""


class ApplicationApproval:
    """A grant minted by application code. The model cannot pass it as an argument."""

    def __init__(self, *, issued: bool) -> None:
        if issued is not True:
            raise TypeError("Call issue_application_approval().")
        self._granted = True

    @property
    def granted(self) -> bool:
        return self._granted


def issue_application_approval() -> ApplicationApproval:
    """Mint a grant the tool registry will accept on the mutate path."""
    return ApplicationApproval(issued=True)
