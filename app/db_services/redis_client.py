import redis
import json

r = redis.Redis(host='localhost', port=6379, db=0)


def add_question_ename(token, question_id, evaluator_name):
    """添加 {question: e_name} 到 token 对应的列表（避免重复）"""
    # 1. 获取所有现有记录
    records = r.lrange(token, 0, -1)
    existing_records = [json.loads(record) for record in records]

    # 2. 检查是否已存在
    for record in existing_records:
        if record["question_id"] == question_id and record["evaluator_name"] == evaluator_name:
            return False

    # 3. 不存在则存入
    r.rpush(token, json.dumps({"question_id": question_id, "evaluator_name": evaluator_name}))
    return True


def get_all_records(token):
    """获取 token 对应的所有 {question_id: evaluator_name} 记录"""
    records = r.lrange(token, 0, -1)  # 获取所有记录
    return [json.loads(record) for record in records]  # 解析 JSON


def delete_record(token, question_id, evaluator_name):
    """删除 token 下匹配的 {question_id: evaluator_name} 记录"""
    target_data = {"question_id": question_id, "evaluator_name": evaluator_name}
    target_json = json.dumps(target_data)

    # 使用 LREM 删除匹配的 JSON 字符串（count=1 表示只删一个）
    deleted_count = r.lrem(token, count=1, value=target_json)
    return deleted_count > 0  # 返回是否删除成功


def delete_all_records(token):
    """删除 token 下的所有记录（清空 List）"""
    r.delete(token)
    return True


# 添加邀请者提交信息
def add_evaluate_info(temporary_token, question_id, evaluator_name, evaluator_id, evaluation_score):
    # 1. 获取所有现有记录
    records = r.lrange(f"evaluator:{temporary_token}", 0, -1)
    existing_records = [json.loads(record) for record in records]

    # 2. 检查是否已存在相同question_id和evaluator_id的记录
    for i, record in enumerate(existing_records):
        if record["question_id"] == question_id and record["evaluator_id"] == evaluator_id:
            # 找到匹配记录，更新评分
            updated_record = {
                "temporary_token": temporary_token,
                "question_id": question_id,
                "evaluator_name": evaluator_name,
                "evaluator_id": evaluator_id,
                "evaluation_score": evaluation_score
            }
            # 替换列表中对应位置的记录
            r.lset(f"evaluator:{temporary_token}", i, json.dumps(updated_record))

    # 3. 不存在则存入新记录
    new_record = json.dumps({
        "temporary_token": temporary_token,
        "question_id": question_id,
        "evaluator_name": evaluator_name,
        "evaluator_id": evaluator_id,
        "evaluation_score": evaluation_score
    })
    print('----------:', new_record)
    r.rpush(f"evaluator:{temporary_token}", new_record)


# 获取某token的所有邀请者提交评价信息
def get_evaluator_records(temporary_token):
    # 获取所有记录
    records = r.lrange(f"evaluator:{temporary_token}", 0, -1)
    # 解析为字典列表并返回
    return [json.loads(record) for record in records]


# 清空所有的邀请者评价信息
def clear_evaluator_records(temporary_token):
    # 删除整个键，清空所有记录
    return r.delete(f"evaluator:{temporary_token}") > 0
