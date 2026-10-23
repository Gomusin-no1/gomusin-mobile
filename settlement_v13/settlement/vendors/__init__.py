"""등록된 거래처 어댑터. 새 거래처는 파일을 만들고 여기에 한 줄 추가한다."""
from .gyeonggi import Gyeonggi
from .juan_kt import JuanKT
from .naeway import Naeway

VENDORS = {v.code: v for v in (Gyeonggi(), JuanKT(), Naeway())}
