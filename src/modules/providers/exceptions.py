from common.exceptions import BaseApplicationError


class FFMPegPreparationError(BaseApplicationError):
    message = "We couldn't prepare file by ffmpeg"


class FFMPegParseError(BaseApplicationError):
    message = "We couldn't parse info from ffmpeg"


class SourceFetchError(BaseApplicationError):
    message = "We couldn't extract info about requested episode."
