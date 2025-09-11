import json
from typing import Dict, Any, List

from app.utils.redis import get_redis


async def add_question_ename(token: str,question_id: str,evaluator_name: str) -> bool:
    """添加 {question: e_name} 到 token 对应的列表（避免重复）"""
    redis_client = await get_redis()
    records = await redis_client.lrange(token, 0, -1)
    existing_records = [json.loads(record) for record in records]

    for record in existing_records:
        if record["question_id"] == question_id and record["evaluator_name"] == evaluator_name:
            return False

    await redis_client.rpush(
        token,
        json.dumps({"question_id": question_id, "evaluator_name": evaluator_name})
    )
    return True

async def get_all_records(token: str) -> List[Dict[str, Any]]:
    """获取 token 对应的所有记录"""
    redis_client = await get_redis()
    records = await redis_client.lrange(token, 0, -1)
    return [json.loads(record) for record in records]

async def delete_record(token: str,question_id: str,evaluator_name: str) -> bool:
    """删除匹配的记录"""
    redis_client = await get_redis()
    target_data = {"question_id": question_id, "evaluator_name": evaluator_name}
    deleted_count = await redis_client.lrem(
        token,
        count=1,
        value=json.dumps(target_data)
    )
    return deleted_count > 0

async def delete_all_records(token: str) -> None:
    """清空 token 下的所有记录"""
    redis_client = await get_redis()
    await redis_client.delete(token)

async def add_evaluate_info(t_token: str,question_id: int,e_name: str,e_id: int,e_score: int) -> None:
    """添加或更新邀请者评价信息"""
    redis_client = await get_redis()
    key = f"evaluator:{t_token}"
    records = await redis_client.lrange(key, 0, -1)
    existing_records = [json.loads(record) for record in records]

    # 检查是否已存在相同 question_id 和 evaluator_id 的记录
    for i, record in enumerate(existing_records):
        if record["question_id"] == question_id and record["evaluator_id"] == e_id:
            # 更新现有记录
            updated_record = {
                "temporary_token": t_token,
                "question_id": question_id,
                "evaluator_name": e_name,
                "evaluator_id": e_id,
                "evaluation_score": e_score
            }
            await redis_client.lset(key, i, json.dumps(updated_record))
            return

    # 添加新记录
    new_record = {
        "temporary_token": t_token,
        "question_id": question_id,
        "evaluator_name": e_name,
        "evaluator_id": e_id,
        "evaluation_score": e_score
    }
    await redis_client.rpush(key, json.dumps(new_record))

async def get_evaluator_records(temporary_token: str) -> List[Dict[str, Any]]:
    """获取某 token 的所有邀请者评价信息"""
    redis_client = await get_redis()
    key = f"evaluator:{temporary_token}"
    records = await redis_client.lrange(key, 0, -1)
    return [json.loads(record) for record in records]

async def clear_evaluator_records(temporary_token: str) -> bool:
    """清空某 token 的所有邀请者评价信息"""
    redis_client = await get_redis()
    key = f"evaluator:{temporary_token}"
    result = await redis_client.delete(key)
    return result > 0