"""
文档管理工具

创建、更新和管理长文档。
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseTool, ToolError
from ..models.tool_models import DocumentInfo

logger = logging.getLogger(__name__)


class DocumentManagerTool(BaseTool):
    """文档管理工具"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.docs_dir = Path(self.config.get("documents_directory", "documents"))
        self.docs_dir.mkdir(exist_ok=True)
    
    @property
    def name(self) -> str:
        return "document_manager"
    
    @property
    def description(self) -> str:
        return "Create, update, and manage long documents. Supports creating new documents, updating existing ones, and retrieving document content."
    
    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "read", "list", "delete"],
                    "description": "Action to perform on documents"
                },
                "document_id": {
                    "type": "string",
                    "description": "Document identifier (required for update, read, delete)"
                },
                "title": {
                    "type": "string",
                    "description": "Document title (required for create)"
                },
                "content": {
                    "type": "string",
                    "description": "Document content in Markdown format (required for create/update)"
                }
            },
            "required": ["action"]
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行文档管理操作
        
        Args:
            action: 操作类型 (create/update/read/list/delete)
            document_id: 文档ID
            title: 文档标题
            content: 文档内容
            
        Returns:
            操作结果
        """
        action = kwargs.get("action")
        
        if action == "create":
            return await self._create_document(kwargs)
        elif action == "update":
            return await self._update_document(kwargs)
        elif action == "read":
            return await self._read_document(kwargs)
        elif action == "list":
            return await self._list_documents()
        elif action == "delete":
            return await self._delete_document(kwargs)
        else:
            raise ToolError(f"Unknown action: {action}")
    
    async def _create_document(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """创建新文档"""
        title = kwargs.get("title")
        content = kwargs.get("content", "")
        
        if not title:
            raise ToolError("Title is required for creating a document")
        
        # 生成文档ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_title = safe_title.replace(' ', '_')[:50]  # 限制长度
        document_id = f"{timestamp}_{safe_title}"
        
        # 创建文档文件
        doc_path = self.docs_dir / f"{document_id}.md"
        
        if doc_path.exists():
            raise ToolError(f"Document with ID {document_id} already exists")
        
        # 写入文档内容
        full_content = f"# {title}\n\n{content}"
        doc_path.write_text(full_content, encoding='utf-8')
        
        # 创建元数据
        metadata = {
            "id": document_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "path": str(doc_path)
        }
        
        metadata_path = self.docs_dir / f"{document_id}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        
        return {
            "action": "create",
            "document_id": document_id,
            "title": title,
            "path": str(doc_path),
            "created_at": metadata["created_at"]
        }
    
    async def _update_document(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """更新文档"""
        document_id = kwargs.get("document_id")
        content = kwargs.get("content")
        
        if not document_id:
            raise ToolError("Document ID is required for updating")
        
        if not content:
            raise ToolError("Content is required for updating")
        
        doc_path = self.docs_dir / f"{document_id}.md"
        metadata_path = self.docs_dir / f"{document_id}.json"
        
        if not doc_path.exists():
            raise ToolError(f"Document {document_id} not found")
        
        # 读取现有元数据
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        else:
            metadata = {
                "id": document_id,
                "title": "Untitled",
                "created_at": datetime.now().isoformat()
            }
        
        # 更新文档内容
        title = metadata.get("title", "Untitled")
        full_content = f"# {title}\n\n{content}"
        doc_path.write_text(full_content, encoding='utf-8')
        
        # 更新元数据
        metadata["updated_at"] = datetime.now().isoformat()
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        
        return {
            "action": "update",
            "document_id": document_id,
            "title": title,
            "updated_at": metadata["updated_at"]
        }
    
    async def _read_document(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """读取文档"""
        document_id = kwargs.get("document_id")
        
        if not document_id:
            raise ToolError("Document ID is required for reading")
        
        doc_path = self.docs_dir / f"{document_id}.md"
        metadata_path = self.docs_dir / f"{document_id}.json"
        
        if not doc_path.exists():
            raise ToolError(f"Document {document_id} not found")
        
        content = doc_path.read_text(encoding='utf-8')
        
        # 读取元数据
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        else:
            metadata = {
                "id": document_id,
                "title": "Untitled",
                "created_at": "Unknown",
                "updated_at": "Unknown"
            }
        
        return {
            "action": "read",
            "document_id": document_id,
            "title": metadata.get("title", "Untitled"),
            "content": content,
            "created_at": metadata.get("created_at", "Unknown"),
            "updated_at": metadata.get("updated_at", "Unknown")
        }
    
    async def _list_documents(self) -> Dict[str, Any]:
        """列出所有文档"""
        documents = []
        
        for md_file in self.docs_dir.glob("*.md"):
            document_id = md_file.stem
            metadata_path = self.docs_dir / f"{document_id}.json"
            
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            else:
                metadata = {
                    "id": document_id,
                    "title": "Untitled",
                    "created_at": "Unknown",
                    "updated_at": "Unknown"
                }
            
            documents.append({
                "id": document_id,
                "title": metadata.get("title", "Untitled"),
                "created_at": metadata.get("created_at", "Unknown"),
                "updated_at": metadata.get("updated_at", "Unknown")
            })
        
        # 按更新时间排序
        documents.sort(key=lambda x: x["updated_at"], reverse=True)
        
        return {
            "action": "list",
            "total_documents": len(documents),
            "documents": documents
        }
    
    async def _delete_document(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """删除文档"""
        document_id = kwargs.get("document_id")
        
        if not document_id:
            raise ToolError("Document ID is required for deletion")
        
        doc_path = self.docs_dir / f"{document_id}.md"
        metadata_path = self.docs_dir / f"{document_id}.json"
        
        if not doc_path.exists():
            raise ToolError(f"Document {document_id} not found")
        
        # 删除文件
        doc_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()
        
        return {
            "action": "delete",
            "document_id": document_id,
            "deleted_at": datetime.now().isoformat()
        }
    
    def format_result_for_ai(self, result: Dict[str, Any]) -> str:
        """格式化文档操作结果供AI使用"""
        if not result["success"]:
            return f"Document operation failed: {result['error']}"
        
        data = result["result"]
        action = data["action"]
        
        if action == "create":
            return f"Document created successfully:\nID: {data['document_id']}\nTitle: {data['title']}\nCreated: {data['created_at']}"
        
        elif action == "update":
            return f"Document updated successfully:\nID: {data['document_id']}\nTitle: {data['title']}\nUpdated: {data['updated_at']}"
        
        elif action == "read":
            content = data["content"]
            if len(content) > 2000:
                content = content[:2000] + "\n\n[Content truncated...]"
            return f"Document content:\nID: {data['document_id']}\nTitle: {data['title']}\n\n{content}"
        
        elif action == "list":
            if not data["documents"]:
                return "No documents found."
            
            doc_list = [f"Total documents: {data['total_documents']}\n"]
            for doc in data["documents"][:10]:  # 限制显示数量
                doc_list.append(f"- {doc['id']}: {doc['title']} (Updated: {doc['updated_at']})")
            
            if len(data["documents"]) > 10:
                doc_list.append(f"... and {len(data['documents']) - 10} more documents")
            
            return "\n".join(doc_list)
        
        elif action == "delete":
            return f"Document deleted successfully:\nID: {data['document_id']}\nDeleted: {data['deleted_at']}"
        
        return str(data)
