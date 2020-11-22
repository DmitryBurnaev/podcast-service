from common.exceptions import BaseApplicationError


class FFMPegPreparationError(BaseApplicationError):
    pass


class YoutubeFetchError(BaseApplicationError):
    message = "We couldn't extract info about requested episode."
