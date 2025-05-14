# -*- coding: utf-8 -*-
import io

import hashlib
import time
import requests

from alibabacloud_bailian20231229.client import Client as bailian20231229Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_bailian20231229 import models as bailian_20231229_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient

from app.config import settings

class BaiLian:
    def __init__(self, file_name, row_data):
        self.work_space = "llm-345t38ujgp85mpr5"  # Workspace ID
        self.CategoryId = "default"  # 所属类目
        self.IndexId = "uqmmobjds5"  # 知识库id
        self.client = self.create_client()
        self.url = ""
        self.method = ""
        self.headers = dict()
        self.lease_id = ""
        self.md_5 = ""
        self.FileId = ""
        self.file_name = file_name
        self.row_data = row_data
        self.file_like = ""

    @staticmethod
    def create_client() -> bailian20231229Client:
        # 使用AK/SK方式进行认证
        config = open_api_models.Config(
            access_key_id=settings.ALI_ACCESS_KEY_ID,
            access_key_secret=settings.ALI_ACCESS_KEY_SECRET,
        )
        # Endpoint 请参考 https://api.aliyun.com/product/bailian
        config.endpoint = f'bailian.cn-beijing.aliyuncs.com'
        return bailian20231229Client(config)


    def calculate_md5(self):
        """
        计算类文件对象的 MD5 值。
        file_like (io.BytesIO 或其他类文件对象): 类文件对象，已包含要计算的数据。
        """
        content = '\n'.join(f'{key}: {value}' for key, value in self.row_data.items())
        # 转换为 bytes 并放入内存文件对象
        self.file_like = io.BytesIO(content.encode('utf-8'))

        md5_hash = hashlib.md5()
        # 确保从头开始读取
        self.file_like.seek(0)
        # 分块读取数据
        for chunk in iter(lambda: self.file_like.read(4096), b""):
            md5_hash.update(chunk)

        # 恢复指针（可选）
        self.file_like.seek(0)
        self.md_5 = md5_hash.hexdigest()


    def apply_file_upload_lease(self) -> None:
        """
        申请文档上传租约
        """
        print("申请文档上传租约")
        apply_file_upload_lease_request = bailian_20231229_models.ApplyFileUploadLeaseRequest(
            file_name=self.file_name,
            md_5=self.md_5,
            size_in_bytes='1000',
            category_type='UNSTRUCTURED'
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            # 复制代码运行请自行打印 API 的返回值
            response = self.client.apply_file_upload_lease_with_options(self.CategoryId,
                                                              self.work_space,
                                                              apply_file_upload_lease_request,
                                                              headers,
                                                              runtime)
            print("响应结果：", response)
            # 获取 Data.Param.Url
            self.url = response.body.data.param.url
            # 获取 Data.Param.Method
            self.method = response.body.data.param.method
            # 获取 Data.Param.Headers 中的 X-bailian-extra
            self.headers = response.body.data.param.headers
            # 获取租约id
            self.lease_id = response.body.data.file_upload_lease_id

            print(self.url, self.method, self.headers, self.lease_id)
        except Exception as error:
            # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
            # 错误 message
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))
            UtilClient.assert_as_string(error.message)

    def upload_file(self):
        """
        上传文档到临时存储
        """
        try:
            # # 读取文档并上传
            # with open(file_path, 'rb') as file:
            #     # 下方设置请求方法用于文档上传，需与您在上一步中调用ApplyFileUploadLease接口实际返回的Data.Param中Method字段的值一致
            #     response = requests.put(self.url, data=file, headers=self.headers)

            response = requests.put(self.url, data=self.file_like, headers=self.headers)

            # 检查响应状态码
            if response.status_code == 200:
                print("File uploaded successfully.")
            else:
                print(f"Failed to upload the file. ResponseCode: {response.status_code}")

        except Exception as e:
            print(f"An error occurred: {str(e)}")

    def add_file(self,) -> None:
        """
        将文档添加到数据管理
        """
        add_file_request = bailian_20231229_models.AddFileRequest(
            lease_id=self.lease_id,
            parser='DASHSCOPE_DOCMIND',
            category_id=self.CategoryId
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            # 复制代码运行请自行打印 API 的返回值
            res = self.client.add_file_with_options(self.work_space, add_file_request, headers, runtime)
            # print(res.body.data.__dir__())
            self.FileId = res.body.data.file_id
            print("添加文件返回：", self.FileId)
        except Exception as error:
            # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
            # 错误 message
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))
            UtilClient.assert_as_string(error.message)


    def describe_file(self):
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            while True:
                print("查询文档解析状态...")
                time.sleep(10)
                res = self.client.describe_file_with_options(self.work_space, self.FileId, headers, runtime)
                if res.body.data.status == "PARSE_SUCCESS":
                    print("文档解析已经完成，可以进行问答使用")
                    break
                print(res)
        except Exception as error:
            # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
            # 错误 message
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))
            UtilClient.assert_as_string(error.message)


    def submit_index_add_documents_job(self):
        """
        向非结构化知识库追加导入已解析的文档
        """
        submit_index_add_documents_job_request = bailian_20231229_models.SubmitIndexAddDocumentsJobRequest(
            index_id=self.IndexId,
            source_type='DATA_CENTER_FILE',
            document_ids=[self.FileId]
        )
        runtime = util_models.RuntimeOptions()
        headers = {}
        try:
            # 复制代码运行请自行打印 API 的返回值
            res = self.client.submit_index_add_documents_job_with_options(self.work_space, submit_index_add_documents_job_request, headers, runtime)
            print("...", res)
        except Exception as error:
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))
            UtilClient.assert_as_string(error.message)


    def main(self):
        self.calculate_md5()
        # 1. 申请文档上传租约
        self.apply_file_upload_lease()
        # 2. 上传文档到临时存储
        self.upload_file()
        # 3. 将文档添加到数据管理
        self.add_file()
        # 4. 查看解析文档状态(需要监听返回，等文档解析完毕后才能执行下一步)
        self.describe_file()
        # 5. 向知识库追加已解析文档
        self.submit_index_add_documents_job()


if __name__ == '__main__':
    file_name = "x.txt"
    row_data = {"总部": "海尼肯总部有三只招财猫"}
    x = BaiLian(file_name, row_data)
    x.main()