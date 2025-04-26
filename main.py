from flask import Flask, send_from_directory, jsonify, request, make_response
import os
from PIL import Image
import ffmpeg
import io
import base64
from datetime import datetime
import time
from functools import lru_cache
import hashlib
from flask_cors import CORS  # 解决跨域问题

app = Flask(__name__)
CORS(app)  # 允许所有跨域请求
BASE_DIR = "D:/BaiduNetdiskDownload/shixi/Tools/beifen"  # 替换为你的视频根目录
THUMBNAIL_DIR = os.path.join(os.path.dirname(__file__), "thumbnails")
SUPPORTED_FORMATS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v']

# 确保缩略图目录存在
os.makedirs(THUMBNAIL_DIR, exist_ok=True)


# 缩略图缓存装饰器
# 缩略图缓存字典（替代lru_cache）
thumbnail_cache = {}


def generate_thumbnail(video_path, thumbnail_path, time='00:00:01'):
    try:
        (
            ffmpeg
            .input(video_path, ss=time)
            .filter('scale', 320, -1)
            .output(thumbnail_path, vframes=1)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True
    except ffmpeg.Error as e:
        print(f"FFmpeg error: {e.stderr.decode('utf8')}")
        return False

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')  # 返回你的前端页面

@app.route('/files/', defaults={'subpath': ''})
@app.route('/files/<path:subpath>')
def list_files(subpath=""):
    # 模拟加载延迟（仅用于演示）
    time.sleep(0.5)

    target_dir = os.path.join(BASE_DIR, subpath)
    items = []

    # 获取排序参数
    sort_by = request.args.get('sort', 'name')  # name, date, size
    reverse = request.args.get('order', 'asc') == 'desc'

    for name in os.listdir(target_dir):
        full_path = os.path.join(target_dir, name)
        is_dir = os.path.isdir(full_path)
        item = {
            "name": name,
            "path": os.path.join(subpath, name),
            "is_dir": is_dir,
            "ext": os.path.splitext(name)[1].lower() if not is_dir else "",
            "date": os.path.getmtime(full_path),
            "size": os.path.getsize(full_path) if not is_dir else 0,
            "is_video": False
        }

        # 仅对视频文件处理缩略图
        if not is_dir and item['ext'] in ['.mp4', '.mkv', '.avi', '.mov']:
            thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
            thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)

            # 获取文件最后修改时间作为缓存依据
            file_mtime = os.path.getmtime(full_path)

            # 检查缓存是否有效
            cache_valid = (
                    thumbnail_name in thumbnail_cache and
                    thumbnail_cache[thumbnail_name] == file_mtime
            )

            if not os.path.exists(thumbnail_path) or not cache_valid:
                if generate_thumbnail(full_path, thumbnail_path):
                    item['has_thumbnail'] = True
                    # 更新缓存记录
                    thumbnail_cache[thumbnail_name] = file_mtime
            else:
                item['has_thumbnail'] = True

            item['thumbnail'] = f"/thumbnail/{thumbnail_name}" if item['has_thumbnail'] else ""

        items.append(item)

    # 排序逻辑
    def get_sort_key(item):
        if sort_by == 'name':
            return item['name'].lower()
        elif sort_by == 'date':
            return item['date']
        elif sort_by == 'size':
            return item['size']
        return item['name'].lower()

    items.sort(key=get_sort_key, reverse=reverse)

    # 转换日期格式用于显示
    for item in items:
        item['date'] = datetime.fromtimestamp(item['date']).strftime('%Y-%m-%d %H:%M')

    response = make_response(jsonify({
        "path": subpath,
        "items": items,
        "sort": sort_by,
        "order": "desc" if reverse else "asc"
    }))
    response.headers['Cache-Control'] = 'no-store'  # 禁用缓存确保实时性
    return response


@app.route('/thumbnail/<filename>')
def get_thumbnail(filename):
    # 设置长期缓存头
    response = make_response(send_from_directory(THUMBNAIL_DIR, filename))
    response.headers['Cache-Control'] = 'public, max-age=31536000'  # 1年缓存
    return response


@app.route('/stream/<path:filename>')
def stream_file(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route('/search')
def search_files():
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify({"error": "No search query provided"}), 400

    results = []
    for root, dirs, files in os.walk(BASE_DIR):
        for name in files + dirs:
            if query in name.lower():
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, BASE_DIR)
                is_dir = os.path.isdir(full_path)
                ext = os.path.splitext(name)[1].lower() if not is_dir else ""

                result = {
                    "name": name,
                    "path": rel_path.replace('\\', '/'),
                    "is_dir": is_dir,
                    "ext": ext,
                    "parent": os.path.dirname(rel_path).replace('\\', '/'),
                    "is_video": ext in SUPPORTED_FORMATS
                }
                results.append(result)

    return jsonify({"results": results})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)