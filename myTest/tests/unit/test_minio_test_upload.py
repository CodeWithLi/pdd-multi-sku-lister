"""MinIO / Alist 测试上传。"""



from unittest.mock import MagicMock, patch



from pdd_agent.integrations.minio.alist_client import AlistUploadResult

from pdd_agent.integrations.minio.config import AlistConfig, MinioConfig, MinioRabbitMQConfig

from pdd_agent.integrations.minio.test_upload import (

    build_test_object_key,

    upload_test_image_set,

)





def _alist_cfg() -> MinioConfig:

    return MinioConfig(

        enabled=True,

        endpoint="127.0.0.1:9000",

        access_key="key",

        secret_key="secret",

        bucket="beilemei-images",

        categories=["笔袋"],

        alist=AlistConfig(

            enabled=True,

            url="https://192.168.1.129",

            username="admin",

            password="123456",

            root_path="/公司电商主图库",

        ),

        rabbitmq=MinioRabbitMQConfig(queue="beilemei.pdd.image.ingest"),

    )





def test_build_test_object_key():

    key = build_test_object_key(

        category="笔袋",

        family_code="BD999",

        image_set="第一套图",

        product_code="BD999A测试笔袋",

        filename="1.jpg",

    )

    assert key == "笔袋/BD999/第一套图/BD999A测试笔袋/1.jpg"





def test_upload_test_image_set_via_alist():

    cfg = _alist_cfg()

    with patch("pdd_agent.integrations.minio.test_upload.login_alist", return_value="token") as login_fn:

        with patch(

            "pdd_agent.integrations.minio.test_upload.upload_bytes_via_alist",

            side_effect=[

                AlistUploadResult(

                    object_key="笔袋/BD999/第一套图/BD999A测试笔袋/1.jpg",

                    virtual_path="/公司电商主图库/笔袋/BD999/第一套图/BD999A测试笔袋/1.jpg",

                ),

                AlistUploadResult(

                    object_key="笔袋/BD999/第一套图/BD999A测试笔袋/2.jpg",

                    virtual_path="/公司电商主图库/笔袋/BD999/第一套图/BD999A测试笔袋/2.jpg",

                ),

            ],

        ) as upload_fn:

            result = upload_test_image_set(

                family_code="BD999",

                product_code="BD999A测试笔袋",

                image_numbers=[1, 2],

                config=cfg,

            )

    login_fn.assert_called_once()

    assert upload_fn.call_count == 2

    assert result.upload_method == "alist"

    assert result.rabbitmq_published == 0

    assert len(result.object_keys) == 2

    assert result.alist_paths[0].startswith("/公司电商主图库/")





def test_upload_test_image_set_minio_debug_publish():

    cfg = MinioConfig(

        enabled=True,

        endpoint="127.0.0.1:9000",

        access_key="key",

        secret_key="secret",

        bucket="beilemei-images",

        categories=["笔袋"],

        rabbitmq=MinioRabbitMQConfig(queue="beilemei.pdd.image.ingest"),

    )



    client = MagicMock()

    with patch("pdd_agent.integrations.minio.test_upload.get_minio_client", return_value=client):

        with patch("pdd_agent.integrations.minio.test_upload.minio_configured", return_value=True):

            with patch(

                "pdd_agent.integrations.minio.test_upload.publish_rabbitmq_upload_notifications",

                return_value=2,

            ) as publish_fn:

                result = upload_test_image_set(

                    family_code="BD999",

                    product_code="BD999A测试笔袋",

                    image_numbers=[1, 2],

                    upload_method="minio",

                    publish_rabbitmq=True,

                    config=cfg,

                )

    assert result.upload_method == "minio"

    assert result.rabbitmq_published == 2

    assert client.put_object.call_count == 2

    publish_fn.assert_called_once()


