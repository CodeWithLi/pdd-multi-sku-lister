import os
import requests
import time
import dashscope
from dashscope import ImageSynthesis

# 请替换为您真实的 API Key
dashscope.api_key = 'sk-xxx'

# 获取本地图片的绝对路径，并加上 file:// 前缀
# 假设基图和代码在同一个文件夹下
local_file_path = os.path.abspath('base_product.jpg')
base_image_uri = f'file://{local_file_path}'

tasks = [
    {
        'name': 'cover_1',
        'prompt': 'Professional e-commerce product shot, clean solid minimalist gradient background, studio lighting, high resolution'
    },
    {
        'name': 'cover_2',
        'prompt': 'E-commerce product lifestyle atmosphere, natural background, elegant environment lighting, beautiful depth of field'
    },
    {
        'name': 'detail_1',
        'prompt': 'Macro shot of product material, extreme close-up, highlighting texture, cinematic lighting'
    },
    {
        'name': 'detail_2',
        'prompt': 'Product display from an alternative angle, high-end commercial photography with elegant props'
    }
]


def download_image(url, save_name):
    img_data = requests.get(url).content
    with open(f'{save_name}.png', 'wb') as handler:
        handler.write(img_data)
    print(f'已成功保存本地文件: {save_name}.png')


for task in tasks:
    print(f"正在通过豆包生成 {task['name']}...")

    # 调用通义万相模型
    rsp = ImageSynthesis.call(
        model=ImageSynthesis.Models.wanx_v1,
        prompt=task['prompt'],
        ref_img=base_image_uri,  # 这里直接传入 file:// 开头的本地路径
        n=1,
        size='1024*1024'
    )

    if rsp.status_code == 200:
        generated_url = rsp.output.results[0].url
        print(f"{task['name']} 接口调用成功，正在下载...")
        download_image(generated_url, task['name'])
    else:
        print(f"生成 {task['name']} 失败，错误码: {rsp.code}, 错误信息: {rsp.message}")

    time.sleep(2)