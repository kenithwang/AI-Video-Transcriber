#!/usr/bin/env python3
"""
一次性脚本：将当前所有频道的视频标记为已处理。
运行后，--watch 模式只会处理之后发布的新视频。
"""

import sys
from pathlib import Path

# 加载 .env
try:
    from dotenv import load_dotenv, find_dotenv
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path)
        print(f"[i] 已加载环境文件: {path}")
except Exception:
    pass

from backend.channel_monitor import ChannelMonitor


def main():
    config_path = Path("channels.yaml")

    if not config_path.exists():
        print(f"[!] 配置文件不存在: {config_path}")
        sys.exit(1)

    monitor = ChannelMonitor(config_path)
    channels = monitor.get_enabled_channels()

    print(f"[i] 已处理视频记录: {monitor._store_path}")
    print(f"[i] 当前已记录: {monitor.store.count()} 个视频")
    print(f"[i] 准备标记 {len(channels)} 个频道的所有视频为已处理...\n")

    total_marked = 0

    for channel in channels:
        display_name = channel.name or channel.url
        print(f"[>] {display_name}")

        try:
            videos = monitor.fetch_channel_videos(channel.url, limit=500)
            print(f"    获取到 {len(videos)} 个视频")

            marked = 0
            for video in videos:
                if not monitor.store.is_processed(video.video_id):
                    monitor.store.mark_processed(
                        video_id=video.video_id,
                        title=video.title,
                        url=video.url,
                        channel_name=video.channel_name,
                        transcript_file=None,  # 标记为已处理但未转录
                    )
                    marked += 1

            print(f"    新标记 {marked} 个视频为已处理")
            total_marked += marked

        except Exception as e:
            print(f"    [!] 错误: {e}")

    print(f"\n{'=' * 40}")
    print(f"完成！共标记 {total_marked} 个视频为已处理")
    print(f"当前已记录: {monitor.store.count()} 个视频")
    print(f"\n之后运行 `python cli.py --watch` 只会处理新发布的视频")


if __name__ == "__main__":
    main()
