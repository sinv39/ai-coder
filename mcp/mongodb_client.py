"""
MongoDB客户端封装
提供工具信息的存储和查询功能
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

logger = logging.getLogger(__name__)


class MongoDBClient:
    """MongoDB客户端封装"""
    
    DATABASE_NAME = "mcp_tools"
    COLLECTION_NAME = "tools"
    
    def __init__(self, host: str = "localhost", port: int = 27017, 
                 database: str = None, username: str = None, password: str = None):
        """
        初始化MongoDB客户端
        
        Args:
            host: MongoDB主机地址
            port: MongoDB端口
            database: 数据库名称（默认使用DATABASE_NAME）
            username: 用户名（可选）
            password: 密码（可选）
        """
        self.host = host
        self.port = port
        self.database_name = database or self.DATABASE_NAME
        
        # 构建连接字符串
        if username and password:
            connection_string = f"mongodb://{username}:{password}@{host}:{port}/{self.database_name}?authSource=admin"
        else:
            connection_string = f"mongodb://{host}:{port}/{self.database_name}"
        
        try:
            self.client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
            # 测试连接
            self.client.admin.command('ping')
            logger.info(f"✅ 成功连接到MongoDB: {host}:{port}")
        except ConnectionFailure as e:
            logger.error(f"❌ 连接MongoDB失败: {str(e)}")
            raise
        
        # 获取数据库和集合
        self.db = self.client[self.database_name]
        self.collection = self.db[self.COLLECTION_NAME]
        
        # 创建索引（提高查询性能）
        self._create_indexes()
    
    def _create_indexes(self):
        """创建索引以提高查询性能"""
        try:
            # 为tool_id创建唯一索引
            self.collection.create_index("tool_id", unique=True)
            # 为server_id创建索引
            self.collection.create_index("server_id")
            # 为tool_name创建索引
            self.collection.create_index("tool_name")
            logger.debug("✅ MongoDB索引创建完成")
        except Exception as e:
            logger.warning(f"创建索引失败（可能已存在）: {str(e)}")
    
    def create_index(self, force: bool = False):
        """
        创建集合（如果不存在）
        
        Args:
            force: 如果为True，清空现有集合
        """
        if force:
            self.clear_index()
        # MongoDB集合会在首次插入时自动创建，这里只需要确保索引存在
        self._create_indexes()
        logger.info(f"✅ 集合准备就绪: {self.database_name}.{self.COLLECTION_NAME}")
    
    def index_tool(self, tool_doc: Dict[str, Any]) -> bool:
        """
        索引单个工具文档（插入或更新）
        
        Args:
            tool_doc: 工具文档字典
            
        Returns:
            是否成功
        """
        try:
            tool_id = tool_doc.get("tool_id")
            if not tool_id:
                raise ValueError("tool_id 不能为空")
            
            # 使用tool_id作为查询条件，upsert操作（存在则更新，不存在则插入）
            self.collection.update_one(
                {"tool_id": tool_id},
                {"$set": tool_doc},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"索引工具失败 {tool_doc.get('tool_id')}: {str(e)}")
            return False
    
    def index_tools_batch(self, tool_docs: List[Dict[str, Any]]) -> int:
        """
        批量索引工具文档
        
        Args:
            tool_docs: 工具文档列表
            
        Returns:
            成功索引的数量
        """
        if not tool_docs:
            return 0
        
        success_count = 0
        try:
            # 使用bulk_write进行批量操作
            from pymongo import UpdateOne
            
            operations = []
            for doc in tool_docs:
                tool_id = doc.get("tool_id")
                if tool_id:
                    operations.append(
                        UpdateOne(
                            {"tool_id": tool_id},
                            {"$set": doc},
                            upsert=True
                        )
                    )
            
            if operations:
                result = self.collection.bulk_write(operations, ordered=False)
                success_count = result.upserted_count + result.modified_count + result.matched_count
                logger.info(f"批量索引: 成功 {success_count} 个, 插入 {result.upserted_count} 个, 更新 {result.modified_count} 个")
            
            return success_count
        except Exception as e:
            logger.error(f"批量索引失败: {str(e)}")
            return 0
    
    def get_tool(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个工具文档
        
        Args:
            tool_id: 工具ID
            
        Returns:
            工具文档，如果不存在则返回None
        """
        try:
            tool = self.collection.find_one({"tool_id": tool_id})
            if tool:
                # 移除MongoDB的_id字段
                tool.pop("_id", None)
            return tool
        except Exception as e:
            logger.error(f"获取工具失败 {tool_id}: {str(e)}")
            return None
    
    def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有已索引的工具
        
        Returns:
            工具文档列表
        """
        try:
            tools = list(self.collection.find({}))
            # 移除MongoDB的_id字段
            for tool in tools:
                tool.pop("_id", None)
            return tools
        except Exception as e:
            logger.error(f"获取所有工具失败: {str(e)}")
            return []
    
    def get_tools_by_server(self, server_id: str) -> List[Dict[str, Any]]:
        """
        获取指定服务器的所有工具
        
        Args:
            server_id: 服务器ID
            
        Returns:
            工具文档列表
        """
        try:
            tools = list(self.collection.find({"server_id": server_id}))
            # 移除MongoDB的_id字段
            for tool in tools:
                tool.pop("_id", None)
            return tools
        except Exception as e:
            logger.error(f"获取服务器 {server_id} 的工具失败: {str(e)}")
            return []
    
    def get_tool_versions(self) -> Dict[str, str]:
        """
        获取所有工具的版本号映射
        
        Returns:
            {tool_id: tool_version} 字典
        """
        try:
            tools = self.collection.find({}, {"tool_id": 1, "tool_version": 1})
            return {tool["tool_id"]: tool.get("tool_version", "") for tool in tools}
        except Exception as e:
            logger.error(f"获取工具版本失败: {str(e)}")
            return {}
    
    def delete_tool(self, tool_id: str) -> bool:
        """
        删除工具文档
        
        Args:
            tool_id: 工具ID
            
        Returns:
            是否成功
        """
        try:
            result = self.collection.delete_one({"tool_id": tool_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"删除工具失败 {tool_id}: {str(e)}")
            return False
    
    def delete_tools_by_server(self, server_id: str) -> int:
        """
        删除指定服务器的所有工具
        
        Args:
            server_id: 服务器ID
            
        Returns:
            删除的数量
        """
        try:
            result = self.collection.delete_many({"server_id": server_id})
            deleted = result.deleted_count
            logger.info(f"删除服务器 {server_id} 的工具: {deleted} 个")
            return deleted
        except Exception as e:
            logger.error(f"删除服务器工具失败 {server_id}: {str(e)}")
            return 0
    
    def clear_index(self):
        """清空集合（删除所有文档）"""
        try:
            result = self.collection.delete_many({})
            logger.info(f"✅ 清空集合: {self.database_name}.{self.COLLECTION_NAME}, 删除了 {result.deleted_count} 个文档")
        except Exception as e:
            logger.error(f"清空集合失败: {str(e)}")

