"""文件夹上传路径与 Alist 上传测试。"""



from unittest.mock import patch



import pytest



from pdd_agent.integrations.minio.config import AlistConfig, MinioConfig

from pdd_agent.integrations.minio.folder_upload import (

    FolderUploadError,

    build_folder_object_key,

    build_material_object_key,

    is_uploadable_image,

    upload_folder_via_alist,

)





def test_build_folder_object_key_with_inner_structure():

    key = build_folder_object_key(

        category="笔袋",

        folder_name="BD021",

        relative_path="第一套图/BD021A卡皮巴拉笔袋/1.jpg",

    )

    assert key == "笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/1.jpg"





def test_build_folder_object_key_when_path_includes_folder_name():

    key = build_folder_object_key(

        category="公仔",

        folder_name="BD021",

        relative_path="BD021/第一套图/BD021A/1.jpg",

    )

    assert key == "公仔/BD021/第一套图/BD021A/1.jpg"


def test_build_material_object_key_image_set_mode():

    key = build_material_object_key(

        category="笔袋",

        upload_mode="image_set",

        folder_name="第二套图",

        relative_path="BD713A/1.jpg",

        target_family="BD713",

    )

    assert key == "笔袋/BD713/第二套图/BD713A/1.jpg"


def test_build_material_object_key_product_mode():

    key = build_material_object_key(

        category="笔袋",

        upload_mode="product",

        folder_name="BD713Z",

        relative_path="1.jpg",

        target_family="BD713",

        target_image_set="第一套图",

    )

    assert key == "笔袋/BD713/第一套图/BD713Z/1.jpg"


def test_build_material_object_key_product_mode_strips_folder_prefix():

    key = build_material_object_key(

        category="笔袋",

        upload_mode="product",

        folder_name="BD713Z",

        relative_path="BD713Z/1.jpg",

        target_family="BD713",

        target_image_set="第一套图",

    )

    assert key == "笔袋/BD713/第一套图/BD713Z/1.jpg"





def test_is_uploadable_image_filters_hidden_and_non_images():

    assert is_uploadable_image("第一套图/BD021A/1.jpg") is True

    assert is_uploadable_image(".DS_Store") is False

    assert is_uploadable_image("第一套图/readme.txt") is False





def test_upload_folder_via_alist_skips_non_images():

    cfg = MinioConfig(

        alist=AlistConfig(

            enabled=True,

            url="https://192.168.1.129",

            username="admin",

            password="123456",

            root_path="/公司电商主图库",

        ),

        bucket="beilemei-images",

    )

    with patch("pdd_agent.integrations.minio.folder_upload.login_alist", return_value="token"):

        with patch("pdd_agent.integrations.minio.folder_upload.upload_bytes_via_alist") as upload_fn:

            result = upload_folder_via_alist(

                category="笔袋",

                folder_name="BD999",

                files=[

                    ("第一套图/BD999A/1.jpg", b"jpeg"),

                    ("第一套图/BD999A/readme.txt", b"txt"),

                ],

                config=cfg,

            )

    upload_fn.assert_called_once()

    assert len(result.object_keys) == 1

    assert result.object_keys[0] == "笔袋/BD999/第一套图/BD999A/1.jpg"

    assert result.skipped == ("第一套图/BD999A/readme.txt",)





def test_upload_folder_rejects_invalid_category():

    cfg = MinioConfig(

        alist=AlistConfig(

            enabled=True,

            url="https://192.168.1.129",

            username="admin",

            password="123456",

        )

    )

    with pytest.raises(FolderUploadError):

        upload_folder_via_alist(

            category="未知类目",

            folder_name="BD999",

            files=[("第一套图/BD999A/1.jpg", b"jpeg")],

            config=cfg,

        )


