class YoutubeException(Exception):
    pass


class YoutubeExtractInfoError(YoutubeException):
    pass


class FFMPegPreparationError(YoutubeException):
    pass
