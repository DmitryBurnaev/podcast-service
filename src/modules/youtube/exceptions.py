from common.exceptions import BaseApplicationError


class FFMPegPreparationError(BaseApplicationError):
    message = "We couldn't prepare file by ffmpeg"


class YoutubeFetchError(BaseApplicationError):
    message = "We couldn't extract info about requested episode."
