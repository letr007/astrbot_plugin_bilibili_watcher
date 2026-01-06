#!/usr/bin/env python3
"""
B站API封装模块
提供获取用户点赞视频等功能的API调用
"""

import json
import logging
from typing import List, Dict, Optional, Any
import requests
from datetime import datetime

logger = logging.getLogger(__name__)


class BilibiliAPI:
    """B站API封装类"""
    
    def __init__(self, sessdata: str = None, timeout: int = 30):
        """
        初始化B站API客户端
        
        Args:
            sessdata: Cookie中的SESSDATA值（访问隐私数据需要）
            timeout: 请求超时时间（秒）
        """
        self.session = requests.Session()
        self.timeout = timeout
        
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
    
    def fetch_user_likes(self, vmid: int) -> Optional[List[Dict]]:
        """
        获取用户的点赞视频列表
        
        Args:
            vmid: 用户MID
            
        Returns:
            视频列表或None（失败时）
        """
        url = "https://api.bilibili.com/x/space/like/video"
        params = {'vmid': vmid}
        
        try:
            logger.info(f"正在获取用户 {vmid} 的点赞视频...")
            response = self.session.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data['code'] == 0:
                if 'data' in data and data['data']:
                    if 'list' in data['data']:
                        videos = data['data']['list']
                        logger.info(f"成功获取用户 {vmid} 的 {len(videos)} 个点赞视频")
                        return videos
                    else:
                        # API返回格式可能直接是数组
                        videos = data['data']
                        logger.info(f"成功获取用户 {vmid} 的 {len(videos)} 个点赞视频")
                        return videos
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
        except Exception as e:
            logger.error(f"获取用户点赞视频时发生未知错误: {e}")
            return None
    
    def fetch_user_info(self, vmid: int) -> Optional[Dict]:
        """
        获取用户基本信息
        
        Args:
            vmid: 用户MID
            
        Returns:
            用户信息字典或None（失败时）
        """
        url = "https://api.bilibili.com/x/space/acc/info"
        params = {'mid': vmid}
        
        try:
            logger.info(f"正在获取用户 {vmid} 的基本信息...")
            response = self.session.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data['code'] == 0:
                user_info = data['data']
                logger.info(f"成功获取用户 {vmid} 的基本信息: {user_info.get('name', '未知')}")
                return user_info
            else:
                logger.error(f"获取用户信息失败: code={data['code']}, message={data['message']}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"请求用户信息失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取用户信息时发生未知错误: {e}")
            return None
    
    def fetch_video_info(self, aid: int) -> Optional[Dict]:
        """
        获取视频详细信息
        
        Args:
            aid: 视频AID
            
        Returns:
            视频信息字典或None（失败时）
        """
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {'aid': aid}
        
        try:
            logger.info(f"正在获取视频 {aid} 的详细信息...")
            response = self.session.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data['code'] == 0:
                video_info = data['data']
                logger.info(f"成功获取视频 {aid} 的信息: {video_info.get('title', '未知')}")
                return video_info
            else:
                logger.error(f"获取视频信息失败: code={data['code']}, message={data['message']}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"请求视频信息失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取视频信息时发生未知错误: {e}")
            return None
    
    def test_connection(self) -> bool:
        """
        测试API连接是否正常
        
        Returns:
            连接是否成功
        """
        try:
            # 使用一个公开的API端点进行测试
            test_url = "https://api.bilibili.com/x/web-interface/nav"
            response = self.session.get(
                test_url,
                headers=self.headers,
                timeout=self.timeout
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"API连接测试失败: {e}")
            return False


if __name__ == "__main__":
    # 测试代码
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    api = BilibiliAPI()
    
    # 测试连接
    if api.test_connection():
        print("✓ API连接测试成功")
    else:
        print("✗ API连接测试失败")
        sys.exit(1)
    
    # 测试获取用户信息（使用一个已知的UID）
    test_uid = 1  # B站官方账号
    user_info = api.fetch_user_info(test_uid)
    if user_info:
        print(f"✓ 成功获取用户信息: {user_info.get('name')}")
    else:
        print("✗ 获取用户信息失败")