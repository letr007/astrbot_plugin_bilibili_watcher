#!/usr/bin/env python3
"""
B站监控插件
监控B站用户的点赞视频，提供查询和更新功能
"""

import re
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 导入自定义模块
from .bilibili_api import BilibiliAPI
from .database_manager import DatabaseManager


@register("bilibili_watcher", "B站监控插件", "监控B站用户的点赞视频，提供查询和更新功能", "1.0.0")
class BilibiliWatcher(Star):
    """B站监控插件主类"""
    
    def __init__(self, context: Context):
        super().__init__(context)
        self.api: Optional[BilibiliAPI] = None
        self.db: Optional[DatabaseManager] = None
        self.config: Dict[str, Any] = {}
        
    async def initialize(self):
        """插件初始化方法"""
        logger.info("B站监控插件初始化中...")
        
        try:
            # 加载配置
            self.config = await self._load_config()
            
            # 初始化API客户端
            sessdata = self.config.get('sessdata')
            self.api = BilibiliAPI(sessdata=sessdata)
            
            # 初始化数据库
            db_path = self.config.get('db_path', 'bilibili_watcher.db')
            self.db = DatabaseManager(db_path)
            
            # 测试API连接（异步）
            if await self.api.test_connection():
                logger.info("✓ B站API连接测试成功")
            else:
                logger.warning("⚠ B站API连接测试失败，部分功能可能受限")
            
            logger.info("✓ B站监控插件初始化完成")
            
        except Exception as e:
            logger.error(f"插件初始化失败: {e}")
            raise
    
    async def _load_config(self) -> Dict[str, Any]:
        """加载插件配置"""
        # 这里可以从插件的配置文件中加载配置
        # 目前使用默认配置
        return {
            'db_path': 'bilibili_watcher.db',
            'update_interval_hours': 6,  # 默认更新间隔
            'cache_enabled': True,
            'max_results': 10,
        }
    
    def _parse_watch_command(self, message: str) -> Optional[Dict[str, Any]]:
        """
        解析/watch命令参数
        
        支持的格式:
        /watch <uid>                    # 查询用户信息
        /watch <uid> --update           # 强制更新
        /watch <uid> --stats            # 显示统计信息
        /watch <uid> --recent <n>       # 显示最近n个点赞
        """
        pattern = r'^/watch\s+(\d+)(?:\s+(--\w+)(?:\s+(\d+))?)?$'
        match = re.match(pattern, message.strip())
        
        if not match:
            return None
        
        uid = int(match.group(1))
        option = match.group(2) if match.group(2) else None
        option_value = match.group(3) if match.group(3) else None
        
        params = {
            'uid': uid,
            'action': 'query',  # 默认操作
        }
        
        if option == '--update':
            params['action'] = 'update'
        elif option == '--stats':
            params['action'] = 'stats'
        elif option == '--recent':
            params['action'] = 'recent'
            params['limit'] = int(option_value) if option_value else 5
        elif option == '--help':
            params['action'] = 'help'
        
        return params
    
    async def _fetch_and_update_user_likes(self, uid: int) -> Dict[str, Any]:
        """获取并更新用户的点赞视频"""
        if not self.api or not self.db:
            return {'success': False, 'message': '插件未正确初始化'}
        
        try:
            # 获取用户点赞视频（异步）
            videos = await self.api.fetch_user_likes(uid)
            
            if videos is None:
                return {'success': False, 'message': '获取数据失败，可能是用户设置了隐私或网络问题'}
            
            if not videos:
                self.db.log_update(uid, 0, 'success')
                return {
                    'success': True,
                    'message': '用户没有点赞视频',
                    'count': 0,
                    'new_count': 0
                }
            
            # 保存视频数据和点赞关系
            saved_count = 0
            new_count = 0
            
            for video in videos:
                # 保存视频信息
                if self.db.save_video(video):
                    saved_count += 1
                    
                    # 检查是否为新的点赞关系
                    if not self.db.user_like_exists(uid, video['aid']):
                        new_count += 1
                    
                    # 保存点赞关系
                    self.db.save_user_like(uid, video['aid'])
            
            # 记录更新日志
            self.db.log_update(uid, len(videos), 'success')
            
            return {
                'success': True,
                'message': f'更新完成: 获取{len(videos)}个视频，保存{saved_count}个，新增{new_count}个点赞',
                'count': len(videos),
                'new_count': new_count,
                'total_count': self.db.get_user_likes_count(uid)
            }
            
        except Exception as e:
            logger.error(f"更新用户点赞视频失败: {e}")
            self.db.log_update(uid, 0, 'failed', str(e))
            return {'success': False, 'message': f'更新失败: {str(e)}'}
    
    async def _get_user_info(self, uid: int) -> Dict[str, Any]:
        """获取用户信息"""
        if not self.api:
            return {'success': False, 'message': 'API未初始化'}
        
        try:
            user_info = await self.api.fetch_user_info(uid)
            if not user_info:
                return {'success': False, 'message': '获取用户信息失败'}
            
            return {
                'success': True,
                'data': user_info
            }
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return {'success': False, 'message': f'获取用户信息失败: {str(e)}'}
    
    async def _format_watch_response(self, params: Dict[str, Any], result: Dict[str, Any]) -> str:
        """格式化/watch命令的响应"""
        uid = params['uid']
        action = params['action']
        
        if not result.get('success', False):
            return f"❌ 操作失败: {result.get('message', '未知错误')}"
        
        if action == 'update':
            return (
                f"✅ 用户 {uid} 点赞视频更新完成！\n"
                f"📊 {result.get('message', '')}\n"
                f"📈 当前总计: {result.get('total_count', 0)} 个点赞视频"
            )
        
        elif action == 'stats':
            if not self.db:
                return "❌ 数据库未初始化"
            
            stats = self.db.get_statistics(uid)
            last_update = self.db.get_last_update_time(uid)
            
            last_update_str = "从未更新"
            if last_update:
                last_update_str = last_update.strftime("%Y-%m-%d %H:%M:%S")
            
            return (
                f"📊 用户 {uid} 统计信息\n"
                f"├ 点赞视频数: {stats.get('user_likes', 0)}\n"
                f"├ 最后更新时间: {last_update_str}\n"
                f"└ 数据库总计: {stats.get('total_videos', 0)} 个视频"
            )
        
        elif action == 'recent':
            if not self.db:
                return "❌ 数据库未初始化"
            
            limit = params.get('limit', 5)
            recent_likes = self.db.get_recent_likes(uid, limit)
            
            if not recent_likes:
                return f"📭 用户 {uid} 暂无点赞记录"
            
            response = f"📅 用户 {uid} 最近 {len(recent_likes)} 个点赞视频:\n"
            for i, like in enumerate(recent_likes, 1):
                title = like['title'][:30] + "..." if len(like['title']) > 30 else like['title']
                response += f"{i}. {title}\n"
                response += f"   👤 {like['owner_name']} | 📅 {self._format_timestamp(like['pubdate'])}\n"
            
            return response
        
        else:  # query action
            if not self.db:
                return "❌ 数据库未初始化"
            
            # 获取用户信息
            user_result = await self._get_user_info(uid)
            user_name = "未知用户"
            if user_result['success']:
                user_name = user_result['data'].get('name', '未知用户')
            
            # 获取统计信息
            likes_count = self.db.get_user_likes_count(uid)
            last_update = self.db.get_last_update_time(uid)
            
            last_update_str = "从未更新"
            update_suggestion = "（建议使用 /watch <uid> --update 进行更新）"
            if last_update:
                last_update_str = last_update.strftime("%Y-%m-%d %H:%M:%S")
                
                # 检查是否需要更新
                if datetime.now() - last_update > timedelta(hours=self.config.get('update_interval_hours', 6)):
                    update_suggestion = "（数据可能已过期，建议使用 --update 更新）"
                else:
                    update_suggestion = "（数据较新）"
            
            return (
                f"👤 用户: {user_name} (UID: {uid})\n"
                f"📊 点赞视频数: {likes_count}\n"
                f"🕒 最后更新时间: {last_update_str} {update_suggestion}\n"
                f"\n"
                f"可用命令:\n"
                f"• /watch {uid} --update    # 强制更新数据\n"
                f"• /watch {uid} --stats     # 查看详细统计\n"
                f"• /watch {uid} --recent 5  # 查看最近5个点赞"
            )
    
    def _format_timestamp(self, timestamp: int) -> str:
        """格式化时间戳为可读字符串"""
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d")
        except:
            return "未知时间"
    
    @event_message_type(EventMessageType.ALL)
    @filter.command("watch")
    async def watch_command(self, event: AstrMessageEvent):
        """
        B站用户监控命令
        用法: /watch <uid> [选项]
        选项:
          --update    强制更新用户点赞视频
          --stats     显示统计信息
          --recent N  显示最近N个点赞视频
          --help      显示帮助信息
        """
        # 检查是否为唤醒命令
        if event.is_at_or_wake_command:
            return
        
        message = event.message_str
        
        # 解析命令参数
        params = self._parse_watch_command(message)
        
        if not params:
            yield event.plain_result(
                "❌ 命令格式错误！\n"
                "正确格式: /watch <uid> [选项]\n"
                "示例: /watch 123456 --update\n"
                "使用 /watch <uid> --help 查看详细帮助"
            )
            return
        
        if params['action'] == 'help':
            yield event.plain_result(
                "📖 B站监控插件帮助\n"
                "\n"
                "命令格式: /watch <uid> [选项]\n"
                "\n"
                "选项说明:\n"
                "• --update    强制更新用户的点赞视频数据\n"
                "• --stats     显示用户的详细统计信息\n"
                "• --recent N  显示用户最近N个点赞视频（默认5个）\n"
                "• --help      显示此帮助信息\n"
                "\n"
                "示例:\n"
                "/watch 123456           # 查询用户信息\n"
                "/watch 123456 --update  # 更新用户数据\n"
                "/watch 123456 --recent 3 # 显示最近3个点赞"
            )
            return
        
        uid = params['uid']
        
        # 根据操作类型执行相应逻辑
        if params['action'] == 'update':
            # 显示正在更新的消息
            yield event.plain_result(f"🔄 正在更新用户 {uid} 的点赞视频，请稍候...")
            
            # 执行更新操作
            result = await self._fetch_and_update_user_likes(uid)
            response = await self._format_watch_response(params, result)
            
        else:
            # 对于查询、统计等操作，直接返回结果
            if params['action'] == 'stats':
                result = {'success': True}
            elif params['action'] == 'recent':
                result = {'success': True}
            else:  # query
                result = {'success': True}
            
            response = await self._format_watch_response(params, result)
        
        yield event.plain_result(response)
    
    @event_message_type(EventMessageType.ALL)
    @filter.command("bilihelp")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        # 检查是否为唤醒命令
        if event.is_at_or_wake_command:
            return
        
        help_text = (
            "🎬 B站监控插件 v1.0.0\n"
            "\n"
            "主要功能:\n"
            "• 监控B站用户的点赞视频\n"
            "• 查询用户点赞统计信息\n"
            "• 自动缓存和更新数据\n"
            "\n"
            "主要命令:\n"
            "• /watch <uid> [选项]  - 监控用户点赞视频\n"
            "• /bilihelp            - 显示此帮助信息\n"
            "\n"
            "使用 /watch <uid> --help 查看详细命令帮助"
        )
        yield event.plain_result(help_text)
    
    async def terminate(self):
        """插件销毁方法"""
        logger.info("B站监控插件正在关闭...")
        # 可以在这里进行资源清理
        logger.info("✓ B站监控插件已关闭")


# 兼容性：保留原有的helloworld命令用于测试
@event_message_type(EventMessageType.ALL)
@filter.command("helloworld")
async def helloworld(self, event: AstrMessageEvent):
    """测试命令"""
    # 检查是否为唤醒命令
    if event.is_at_or_wake_command:
        return
    
    user_name = event.get_sender_name()
    yield event.plain_result(f"Hello, {user_name}! B站监控插件已就绪。")
