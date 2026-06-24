"""Alist 路径与客户端测试。"""



from unittest.mock import MagicMock, patch



from pdd_agent.integrations.minio.alist_client import (

    alist_object_key,

    alist_virtual_path,

    upload_bytes_via_alist,

)

from pdd_agent.integrations.minio.config import AlistConfig, MinioConfig





def _cfg() -> MinioConfig:

    return MinioConfig(

        alist=AlistConfig(

            enabled=True,

            url="https://192.168.1.129",

            username="admin",

            password="123456",

            root_path="/公司电商主图库",

        )

    )





def test_alist_virtual_path_roundtrip():

    cfg = _cfg()

    key = "笔袋/BD999/第一套图/BD999A测试笔袋/1.jpg"

    virtual = alist_virtual_path(key, config=cfg)

    assert virtual == "/公司电商主图库/笔袋/BD999/第一套图/BD999A测试笔袋/1.jpg"

    assert alist_object_key(virtual, config=cfg) == key





def test_upload_bytes_via_alist_sends_encoded_file_path():

    cfg = _cfg()

    response = MagicMock()

    response.json.return_value = {"code": 200, "message": "success", "data": None}



    client = MagicMock()

    client.__enter__.return_value = client

    client.put.return_value = response

    client.post.return_value = response



    with patch("pdd_agent.integrations.minio.alist_client._alist_client", return_value=client):

        result = upload_bytes_via_alist(

            "笔袋/BD999/第一套图/BD999A测试笔袋/1.jpg",

            b"jpeg",

            token="token",

            config=cfg,

        )



    put_call = client.put.call_args

    headers = put_call.kwargs["headers"]

    assert headers["Authorization"] == "token"

    assert "%E7%AC%94%E8%A2%8B" in headers["File-Path"]

    assert result.virtual_path.endswith("/1.jpg")


