#!/usr/bin/env python3
"""
数据库管理模块
管理SQLite数据库的连接和操作
"""

import sqlite3
import logging
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理类"""
    
    def __init__(self, db_path: str = "bilibili_watcher.db"):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 创建视频基本信息表（简化版）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                aid INTEGER PRIMARY KEY,
                bvid TEXT UNIQUE,
                title TEXT NOT NULL,
                pubdate INTEGER,
                owner_mid INTEGER,
                owner_name TEXT,
                pic TEXT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 创建用户点赞关系表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_mid INTEGER NOT NULL,
                aid INTEGER NOT NULL,
                collect_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_mid, aid)
            )
            ''')
            
            # 创建更新记录表（简化版）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS update_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_mid INTEGER NOT NULL,
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_fetched INTEGER DEFAULT 0,
                status TEXT DEFAULT 'success'
            )
            ''')
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_likes_user ON user_likes(user_mid)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_likes_aid ON user_likes(aid)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_update_log_user ON update_log(user_mid)')
            
            conn.commit()
            logger.info(f"数据库初始化完成: {self.db_path}")
            
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
        finally:
            if 'conn' in locals():
                conn.close()
    
    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def video_exists(self, aid: int) -> bool:
        """检查视频是否已存在"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM videos WHERE aid = ?", (aid,))
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception as e:
            logger.error(f"检查视频存在性失败: {e}")
            return False
    
    def user_like_exists(self, user_mid: int, aid: int) -> bool:
        """检查用户点赞关系是否已存在"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM user_likes WHERE user_mid = ? AND aid = ?",
                (user_mid, aid)
            )
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception as e:
            logger.error(f"检查用户点赞关系失败: {e}")
            return False
    
    def save_video(self, video_data: Dict) -> bool:
        """保存视频数据到数据库"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 提取视频基本信息
            aid = video_data.get('aid')
            bvid = video_data.get('bvid', '')
            title = video_data.get('title', '')
            pubdate = video_data.get('pubdate', 0)
            
            # 提取UP主信息
            owner = video_data.get('owner', {})
            owner_mid = owner.get('mid', 0) if owner else 0
            owner_name = owner.get('name', '') if owner else ''
            
            pic = video_data.get('pic', '')
            
            # 插入或更新视频信息
            cursor.execute('''
            INSERT OR REPLACE INTO videos (aid, bvid, title, pubdate, owner_mid, owner_name, pic)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (aid, bvid, title, pubdate, owner_mid, owner_name, pic))
            
            conn.commit()
            conn.close()
            logger.debug(f"保存视频数据成功: aid={aid}, title={title[:20]}...")
            return True
            
        except Exception as e:
            logger.error(f"保存视频数据失败 (aid={video_data.get('aid', 'N/A')}): {e}")
            return False
    
    def save_user_like(self, user_mid: int, aid: int) -> bool:
        """保存用户点赞关系"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT OR IGNORE INTO user_likes (user_mid, aid)
            VALUES (?, ?)
            ''', (user_mid, aid))
            
            conn.commit()
            conn.close()
            logger.debug(f"保存用户点赞关系成功: user_mid={user_mid}, aid={aid}")
            return True
            
        except Exception as e:
            logger.error(f"保存用户点赞关系失败: {e}")
            return False
    
    def log_update(self, user_mid: int, total_fetched: int, status: str = 'success'):
        """记录更新日志"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            INSERT INTO update_log (user_mid, total_fetched, status)
            VALUES (?, ?, ?)
            ''', (user_mid, total_fetched, status))
            
            conn.commit()
            conn.close()
            logger.debug(f"记录更新日志成功: user_mid={user_mid}, fetched={total_fetched}")
            
        except Exception as e:
            logger.error(f"记录更新日志失败: {e}")
    
    def get_user_likes_count(self, user_mid: int) -> int:
        """获取用户的点赞视频数量"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT COUNT(*) FROM user_likes WHERE user_mid = ?",
                (user_mid,)
            )
            count = cursor.fetchone()[0]
            
            conn.close()
            return count
            
        except Exception as e:
            logger.error(f"获取用户点赞数量失败: {e}")
            return 0
    
    def get_last_update_time(self, user_mid: int) -> Optional[datetime]:
        """获取用户最后更新时间"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT last_update FROM update_log WHERE user_mid = ? ORDER BY id DESC LIMIT 1",
                (user_mid,)
            )
            result = cursor.fetchone()
            
            conn.close()
            
            if result and result[0]:
                # 将字符串转换为datetime对象
                return datetime.fromisoformat(result[0].replace('Z', '+00:00'))
            return None
            
        except Exception as e:
            logger.error(f"获取最后更新时间失败: {e}")
            return None
    
    def get_recent_likes(self, user_mid: int, limit: int = 5, fields: List[str] = None) -> List[Dict]:
        """获取用户最近的点赞视频
        
        Args:
            user_mid: 用户MID
            limit: 返回数量限制
            fields: 指定返回的字段列表，如果为None则返回所有字段
            
        Returns:
            视频信息字典列表
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 默认字段
            default_fields = ['aid', 'bvid', 'title', 'owner_name', 'pubdate', 'collect_time']
            
            if fields is None:
                fields = default_fields
            
            # 构建SELECT子句
            field_mapping = {
                'aid': 'v.aid',
                'bvid': 'v.bvid',
                'title': 'v.title',
                'owner_name': 'v.owner_name',
                'pubdate': 'v.pubdate',
                'collect_time': 'ul.collect_time',
                'owner_mid': 'v.owner_mid',
                'pic': 'v.pic'
            }
            
            select_fields = []
            for field in fields:
                if field in field_mapping:
                    select_fields.append(f"{field_mapping[field]} as {field}")
                else:
                    # 如果字段不在映射中，使用原字段名
                    select_fields.append(field)
            
            select_clause = ', '.join(select_fields)
            
            cursor.execute(f'''
            SELECT {select_clause}
            FROM user_likes ul
            JOIN videos v ON ul.aid = v.aid
            WHERE ul.user_mid = ?
            ORDER BY ul.collect_time DESC
            LIMIT ?
            ''', (user_mid, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            # 转换为字典列表
            result = []
            for row in rows:
                video_dict = {}
                for i, field in enumerate(fields):
                    video_dict[field] = row[i]
                result.append(video_dict)
            
            return result
            
        except Exception as e:
            logger.error(f"获取最近点赞视频失败: {e}")
            return []
    
    def get_statistics(self, user_mid: int = None) -> Dict:
        """获取统计信息"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            stats = {}
            
            # 总视频数
            cursor.execute("SELECT COUNT(*) FROM videos")
            stats['total_videos'] = cursor.fetchone()[0]
            
            # 总点赞记录数
            cursor.execute("SELECT COUNT(*) FROM user_likes")
            stats['total_likes'] = cursor.fetchone()[0]
            
            # 不同用户数
            cursor.execute("SELECT COUNT(DISTINCT user_mid) FROM user_likes")
            stats['unique_users'] = cursor.fetchone()[0]
            
            # 最近更新时间
            cursor.execute("SELECT MAX(last_update) FROM update_log WHERE status = 'success'")
            stats['last_update'] = cursor.fetchone()[0]
            
            # 用户特定统计
            if user_mid:
                cursor.execute("SELECT COUNT(*) FROM user_likes WHERE user_mid = ?", (user_mid,))
                stats['user_likes'] = cursor.fetchone()[0]
                
                cursor.execute(
                    "SELECT last_update FROM update_log WHERE user_mid = ? ORDER BY id DESC LIMIT 1",
                    (user_mid,)
                )
                result = cursor.fetchone()
                stats['user_last_update'] = result[0] if result else None
            
            conn.close()
            return stats
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}


if __name__ == "__main__":
    # 测试代码
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建数据库管理器
    db = DatabaseManager("test.db")
    
    # 测试视频保存
    test_video = {
        'aid': 123456,
        'bvid': 'BV1test',
        'title': '测试视频标题',
        'pubdate': 1640995200,
        'owner': {'mid': 1001, 'name': '测试UP主'},
        'pic': 'https://example.com/pic.jpg'
    }
    
    if db.save_video(test_video):
        print("✓ 视频保存成功")
    else:
        print("✗ 视频保存失败")
    
    # 测试用户点赞关系
    if db.save_user_like(1001, 123456):
        print("✓ 用户点赞关系保存成功")
    else:
        print("✗ 用户点赞关系保存失败")
    
    # 测试更新日志
    db.log_update(1001, 1)
    print("✓ 更新日志记录成功")
    
    # 测试统计信息
    stats = db.get_statistics(1001)
    print(f"✓ 统计信息获取成功: {stats}")
    
    # 清理测试数据库
    import os
    if os.path.exists("test.db"):
        os.remove("test.db")
        print("✓ 测试数据库清理完成")