#!/usr/bin/env python3
"""
B站用户点赞视频爬虫
功能：定时增量更新特定用户的点赞视频到SQLite数据库
API: https://api.bilibili.com/x/space/like/video
"""

import sqlite3
import json
import time
import requests
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import schedule
import argparse
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bilibili_likes.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('BilibiliLikesSpider')


class BilibiliLikesSpider:
    def __init__(self, db_path: str = 'bilibili_likes.db', sessdata: str = None):
        """
        初始化爬虫
        
        Args:
            db_path: SQLite数据库路径
            sessdata: Cookie中的SESSDATA值（可选，公开数据可不设置）
        """
        self.db_path = db_path
        self.session = requests.Session()
        self.base_url = "https://api.bilibili.com/x/space/like/video"
        
        # 设置请求头
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://space.bilibili.com/',
            'Accept': 'application/json, text/plain, */*',
        }
        
        # 设置Cookie（如果需要访问隐私数据）
        if sessdata:
            self.session.cookies.set('SESSDATA', sessdata, domain='.bilibili.com')
            logger.info("已设置SESSDATA Cookie")
        
        # 初始化数据库
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建视频基本信息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            aid INTEGER PRIMARY KEY,
            bvid TEXT UNIQUE,
            title TEXT NOT NULL,
            duration INTEGER,
            pubdate INTEGER,
            ctime INTEGER,
            tid INTEGER,
            tname TEXT,
            desc TEXT,
            pic TEXT,
            owner_mid INTEGER,
            owner_name TEXT,
            copyright INTEGER,
            state INTEGER,
            pub_location TEXT,
            short_link TEXT,
            first_frame TEXT,
            subtitle TEXT,
            resource_type TEXT,
            enable_vt INTEGER,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建视频统计数据表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aid INTEGER,
            view INTEGER,
            danmaku INTEGER,
            reply INTEGER,
            favorite INTEGER,
            coin INTEGER,
            share INTEGER,
            like_count INTEGER,
            now_rank INTEGER,
            his_rank INTEGER,
            vt INTEGER,
            vv INTEGER,
            collect_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (aid) REFERENCES videos (aid) ON DELETE CASCADE
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
        
        # 创建维度信息表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_dimension (
            aid INTEGER PRIMARY KEY,
            width INTEGER,
            height INTEGER,
            rotate INTEGER,
            FOREIGN KEY (aid) REFERENCES videos (aid) ON DELETE CASCADE
        )
        ''')
        
        # 创建更新记录表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS update_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_mid INTEGER NOT NULL,
            last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_fetched INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            error_msg TEXT
        )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_likes_user ON user_likes(user_mid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_likes_aid ON user_likes(aid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_pubdate ON videos(pubdate DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_update_log_user ON update_log(user_mid)')
        
        conn.commit()
        conn.close()
        logger.info(f"数据库初始化完成: {self.db_path}")
    
    def fetch_user_likes(self, vmid: int) -> Optional[List[Dict]]:
        """
        获取用户的点赞视频列表
        
        Args:
            vmid: 用户MID
            
        Returns:
            视频列表或None（失败时）
        """
        params = {'vmid': vmid}
        
        try:
            response = self.session.get(
                self.base_url,
                params=params,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data['code'] == 0:
                if 'data' in data and data['data']:
                    if 'list' in data['data']:
                        return data['data']['list']
                    else:
                        # API返回格式可能直接是数组
                        return data['data']
                else:
                    logger.warning(f"用户 {vmid} 没有点赞数据或数据为空")
                    return []
            elif data['code'] == 53013:
                logger.error(f"用户 {vmid} 设置了隐私，需要登录")
                return None
            else:
                logger.error(f"API返回错误: code={data['code']}, message={data['message']}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return None
    
    def video_exists(self, conn: sqlite3.Connection, aid: int) -> bool:
        """检查视频是否已存在"""
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM videos WHERE aid = ?", (aid,))
        return cursor.fetchone() is not None
    
    def user_like_exists(self, conn: sqlite3.Connection, user_mid: int, aid: int) -> bool:
        """检查用户点赞关系是否已存在"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_likes WHERE user_mid = ? AND aid = ?",
            (user_mid, aid)
        )
        return cursor.fetchone() is not None
    
    def save_video_data(self, conn: sqlite3.Connection, video_data: Dict) -> bool:
        """保存视频数据到数据库（如果不存在则插入）"""
        try:
            cursor = conn.cursor()
            
            # 检查是否已存在
            if self.video_exists(conn, video_data['aid']):
                return True
            
            # 插入视频基本信息
            cursor.execute('''
            INSERT OR IGNORE INTO videos (
                aid, bvid, title, duration, pubdate, ctime, tid, tname, desc, pic,
                owner_mid, owner_name, copyright, state, pub_location, short_link,
                first_frame, subtitle, resource_type, enable_vt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                video_data['aid'],
                video_data.get('bvid', ''),
                video_data.get('title', ''),
                video_data.get('duration', 0),
                video_data.get('pubdate', 0),
                video_data.get('ctime', 0),
                video_data.get('tid', 0),
                video_data.get('tname', ''),
                video_data.get('desc', '')[:500],  # 限制描述长度
                video_data.get('pic', ''),
                video_data['owner']['mid'] if 'owner' in video_data else 0,
                video_data['owner']['name'] if 'owner' in video_data else '',
                video_data.get('copyright', 0),
                video_data.get('state', 0),
                video_data.get('pub_location', ''),
                video_data.get('short_link_v2', ''),
                video_data.get('first_frame', ''),
                video_data.get('subtitle', ''),
                video_data.get('resource_type', ''),
                video_data.get('enable_vt', 0)
            ))
            
            # 插入视频统计数据
            if 'stat' in video_data:
                stat = video_data['stat']
                cursor.execute('''
                INSERT INTO video_stats (
                    aid, view, danmaku, reply, favorite, coin, share,
                    like_count, now_rank, his_rank, vt, vv
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video_data['aid'],
                    stat.get('view', 0),
                    stat.get('danmaku', 0),
                    stat.get('reply', 0),
                    stat.get('favorite', 0),
                    stat.get('coin', 0),
                    stat.get('share', 0),
                    stat.get('like', 0),  # API返回的是like，不是like_count
                    stat.get('now_rank', 0),
                    stat.get('his_rank', 0),
                    stat.get('vt', 0),
                    stat.get('vv', 0)
                ))
            
            # 插入维度信息
            if 'dimension' in video_data:
                dim = video_data['dimension']
                cursor.execute('''
                INSERT OR REPLACE INTO video_dimension (aid, width, height, rotate)
                VALUES (?, ?, ?, ?)
                ''', (
                    video_data['aid'],
                    dim.get('width', 0),
                    dim.get('height', 0),
                    dim.get('rotate', 0)
                ))
            
            return True
            
        except Exception as e:
            logger.error(f"保存视频数据失败 (aid={video_data.get('aid', 'N/A')}): {e}")
            return False
    
    def save_user_like(self, conn: sqlite3.Connection, user_mid: int, aid: int) -> bool:
        """保存用户点赞关系"""
        try:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT OR IGNORE INTO user_likes (user_mid, aid)
            VALUES (?, ?)
            ''', (user_mid, aid))
            return True
        except Exception as e:
            logger.error(f"保存用户点赞关系失败: {e}")
            return False
    
    def log_update(self, conn: sqlite3.Connection, user_mid: int, 
                   total_fetched: int, status: str = 'success', 
                   error_msg: str = None):
        """记录更新日志"""
        try:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO update_log (user_mid, total_fetched, status, error_msg)
            VALUES (?, ?, ?, ?)
            ''', (user_mid, total_fetched, status, error_msg))
        except Exception as e:
            logger.error(f"记录更新日志失败: {e}")
    
    def update_user_likes(self, user_mid: int) -> Tuple[bool, str]:
        """
        更新指定用户的点赞视频
        
        Args:
            user_mid: 用户MID
            
        Returns:
            (是否成功, 消息)
        """
        logger.info(f"开始更新用户 {user_mid} 的点赞视频...")
        
        # 获取点赞视频列表
        videos = self.fetch_user_likes(user_mid)
        
        if videos is None:
            error_msg = "获取数据失败"
            logger.error(error_msg)
            
            # 记录失败日志
            conn = sqlite3.connect(self.db_path)
            self.log_update(conn, user_mid, 0, 'failed', error_msg)
            conn.close()
            
            return False, error_msg
        
        if not videos:
            logger.info(f"用户 {user_mid} 没有点赞视频")
            
            # 记录成功日志（无数据）
            conn = sqlite3.connect(self.db_path)
            self.log_update(conn, user_mid, 0, 'success', 'no videos')
            conn.close()
            
            return True, "没有点赞视频"
        
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        
        try:
            saved_count = 0
            new_count = 0
            
            for video in videos:
                # 保存视频数据
                if self.save_video_data(conn, video):
                    saved_count += 1
                    
                    # 检查是否为新的点赞关系
                    if not self.user_like_exists(conn, user_mid, video['aid']):
                        new_count += 1
                    
                    # 保存用户点赞关系
                    self.save_user_like(conn, user_mid, video['aid'])
            
            # 记录更新日志
            self.log_update(conn, user_mid, len(videos), 'success')
            
            conn.commit()
            
            msg = f"更新完成: 获取{len(videos)}个视频，保存{saved_count}个，新增{new_count}个点赞"
            logger.info(msg)
            
            return True, msg
            
        except Exception as e:
            conn.rollback()
            error_msg = f"数据库操作失败: {e}"
            logger.error(error_msg)
            self.log_update(conn, user_mid, 0, 'failed', error_msg)
            return False, error_msg
            
        finally:
            conn.close()
    
    def get_statistics(self, user_mid: int = None) -> Dict:
        """获取统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        try:
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
        
        finally:
            conn.close()
        
        return stats
    
    def run_scheduled(self, user_mid: int, interval_hours: int = 6):
        """
        定时运行爬虫
        
        Args:
            user_mid: 用户MID
            interval_hours: 间隔小时数
        """
        logger.info(f"启动定时任务，每{interval_hours}小时更新一次用户 {user_mid}")
        
        def job():
            logger.info("=== 定时任务开始 ===")
            success, msg = self.update_user_likes(user_mid)
            logger.info(f"定时任务结束: {'成功' if success else '失败'} - {msg}")
            logger.info("=== 定时任务结束 ===\n")
        
        # 立即运行一次
        job()
        
        # 设置定时任务
        schedule.every(interval_hours).hours.do(job)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
        except KeyboardInterrupt:
            logger.info("程序被用户中断")
        except Exception as e:
            logger.error(f"定时任务异常: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='B站用户点赞视频爬虫')
    parser.add_argument('--mid', type=int, required=True, help='用户MID')
    parser.add_argument('--sessdata', type=str, help='SESSDATA Cookie值（访问隐私数据需要）')
    parser.add_argument('--db', type=str, default='bilibili_likes.db', help='数据库文件路径')
    parser.add_argument('--interval', type=int, default=6, help='更新间隔（小时）')
    parser.add_argument('--once', action='store_true', help='只运行一次，不启用定时任务')
    parser.add_argument('--stats', action='store_true', help='显示统计信息')
    
    args = parser.parse_args()
    
    # 创建爬虫实例
    spider = BilibiliLikesSpider(db_path=args.db, sessdata=args.sessdata)
    
    # 显示统计信息
    if args.stats:
        stats = spider.get_statistics(args.mid)
        print("\n=== 数据库统计信息 ===")
        print(f"总视频数: {stats.get('total_videos', 0)}")
        print(f"总点赞记录数: {stats.get('total_likes', 0)}")
        print(f"不同用户数: {stats.get('unique_users', 0)}")
        print(f"最近更新时间: {stats.get('last_update', 'N/A')}")
        
        if 'user_likes' in stats:
            print(f"\n用户 {args.mid} 统计:")
            print(f"  点赞视频数: {stats['user_likes']}")
            print(f"  最后更新: {stats.get('user_last_update', 'N/A')}")
        return
    
    # 运行爬虫
    if args.once:
        # 单次运行
        success, msg = spider.update_user_likes(args.mid)
        if success:
            print(f"✓ 更新成功: {msg}")
        else:
            print(f"✗ 更新失败: {msg}")
            sys.exit(1)
    else:
        # 定时运行
        spider.run_scheduled(args.mid, args.interval)


if __name__ == "__main__":
    main()