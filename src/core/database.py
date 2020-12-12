from gino_starlette import Gino
import sqlalchemy

from core import settings


class GinoDB(Gino):
    Column: sqlalchemy.Column
    ForeignKey: sqlalchemy.ForeignKey
    Integer: sqlalchemy.Integer
    String: sqlalchemy.String
    Text: sqlalchemy.Text
    Boolean: sqlalchemy.Boolean
    DateTime: sqlalchemy.DateTime
    Date: sqlalchemy.Date


db = GinoDB(
    dsn=settings.DATABASE_DSN,
    pool_min_size=settings.DATABASE["pool_min_size"],
    pool_max_size=settings.DATABASE["pool_max_size"],
    echo=settings.DATABASE["echo"],
    ssl=settings.DATABASE["ssl"],
    use_connection_for_request=settings.DATABASE["use_connection_for_request"],
    retry_limit=settings.DATABASE["retry_limit"],
    retry_interval=settings.DATABASE["retry_interval"],
)
