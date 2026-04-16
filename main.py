import os
import hashlib
from datetime import datetime
from flask import Flask, send_from_directory, jsonify, request, render_template, Response
import ffmpeg

app = Flask(__name__)
BASE_DIR = "D:/BaiduNetdiskDownload/shixi/Tools/beifen"  # 替换为你的实际视频目录
THUMBNAIL_DIR = os.path.join(os.path.dirname(__file__), "thumbnails")
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# 支持的文件类型
VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.rmvb']
IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']

import chardet

MAX_TEXT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
TEXT_EXTS = {
    '.txt', '.log', '.md', '.json', '.xml', '.yml', '.yaml',
    '.ini', '.cfg', '.conf', '.csv', '.tsv', '.sql', '.sh',
    '.bat', '.py', '.js', '.html', '.htm', '.css', '.env',
    '.rst', '.tex', '.go', '.rs', '.java', '.c', '.cpp', '.h'
}
def generate_thumbnail(file_path, thumbnail_path):
    try:
        ext = os.path.splitext(file_path)[1].lower()

        if ext in VIDEO_EXTS:
            # 使用ffmpeg获取视频中间帧
            probe = ffmpeg.probe(file_path)
            duration = float(probe['format']['duration'])
            middle_time = duration / 2

            (
                ffmpeg.input(file_path, ss=middle_time)
                .filter('scale', 320, -1)
                .output(thumbnail_path, vframes=1)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            return True

        elif ext in IMAGE_EXTS:
            from PIL import Image
            img = Image.open(file_path)
            img.thumbnail((320, 320))
            img.save(thumbnail_path)
            return True

        return False
    except Exception as e:
        print(f"生成缩略图失败: {str(e)}")
        return False


@app.route('/files/', defaults={'subpath': ''})
@app.route('/files/<path:subpath>')
def list_files(subpath):
    try:
        # 规范化路径并添加 UNC 前缀以支持长路径（Windows 特有）
        target_dir = os.path.normpath(os.path.join(BASE_DIR, subpath))

        if os.name == 'nt':
            target_dir = r'\\?\{}'.format(target_dir)

        if not os.path.exists(target_dir):
            return jsonify({"error": f"路径不存在: {subpath}"}), 404

        sort_by = request.args.get('sort', 'type')
        order = request.args.get('order', 'desc' if sort_by == 'date' else 'asc')

        items = []
        for name in os.listdir(target_dir):
            full_path = os.path.join(target_dir, name)
            is_dir = os.path.isdir(full_path)
            ext = os.path.splitext(name)[1].lower()

            # 初始化缩略图相关字段（异步模式下只检查是否已存在）
            has_thumbnail = False
            thumbnail = ""

            if not is_dir and (ext in VIDEO_EXTS or ext in IMAGE_EXTS):
                thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
                thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)

                # 只检查是否已存在，不再生成（异步生成由前端触发）
                if os.path.exists(thumbnail_path):
                    has_thumbnail = True
                    thumbnail = f"/thumbnail/{thumbnail_name}"

            item = {
                "name": name,
                "path": os.path.join(subpath, name).replace('\\', '/'),
                "is_dir": is_dir,
                "ext": ext,
                "date": os.path.getmtime(full_path),
                "size": os.path.getsize(full_path) if not is_dir else 0,
                "type": 0 if is_dir else (1 if ext in VIDEO_EXTS else (2 if ext in IMAGE_EXTS else 3)),
                "is_video": ext in VIDEO_EXTS,
                "is_image": ext in IMAGE_EXTS,
                "has_thumbnail": has_thumbnail,
                "thumbnail": thumbnail,
                "timestamp": os.path.getctime(full_path)
            }

            items.append(item)

        # 排序逻辑
        items.sort(key=lambda x: (
            x['type'],
            -x['date'] if sort_by == 'date' and order == 'desc' else x['date'],
            x['name'].lower()
        ))

        # 转换日期格式
        for item in items:
            item['date'] = datetime.fromtimestamp(item['date']).strftime('%Y-%m-%d %H:%M')

        return jsonify({
            "path": subpath,
            "items": items,
            "parent": os.path.dirname(subpath).replace('\\', '/') if subpath else None
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/thumbnail/<filename>')
def get_thumbnail(filename):
    return send_from_directory(THUMBNAIL_DIR, filename)


import mimetypes


@app.route('/stream/<path:filename>')
def stream_file(filename):
    safe_path = os.path.join(BASE_DIR, filename)
    if not os.path.abspath(safe_path).startswith(os.path.abspath(BASE_DIR)):
        return "Forbidden", 403
    if not os.path.exists(safe_path):
        return "File not found", 404

    ext = os.path.splitext(filename)[1].lower()

    # 非文本文件：直接发送（二进制）
    if ext not in TEXT_EXTS:
        return send_from_directory(BASE_DIR, filename)

    # 文本文件：读取并转为 UTF-8
    file_size = os.path.getsize(safe_path)
    if file_size > MAX_TEXT_FILE_SIZE:
        return "File too large to preview (max 10MB)", 400

    try:
        with open(safe_path, 'rb') as f:
            raw_data = f.read()

        # 检测编码
        detected = chardet.detect(raw_data)
        encoding = detected['encoding']
        confidence = detected['confidence']

        # 如果检测失败，默认用 GBK（中文 Windows 常见）
        if not encoding or confidence < 0.6:
            encoding = 'gbk'

        # 尝试解码
        try:
            text = raw_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            # 如果失败，尝试 fallback
            text = raw_data.decode('utf-8', errors='replace')

        # 返回 UTF-8 文本
        return Response(text, mimetype='text/plain; charset=utf-8')

    except Exception as e:
        return f"Failed to read file: {str(e)}", 500


@app.route('/search')
def search_files():
    try:
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
                    ctime = os.path.getctime(full_path)

                    # 初始化缩略图相关字段（异步模式下只检查是否已存在）
                    has_thumbnail = False
                    thumbnail = ""

                    if not is_dir and (ext in VIDEO_EXTS or ext in IMAGE_EXTS):
                        thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
                        thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)

                        # 只检查是否已存在，不再生成（异步生成由前端触发）
                        if os.path.exists(thumbnail_path):
                            has_thumbnail = True
                            thumbnail = f"/thumbnail/{thumbnail_name}"

                    # 确定文件类型优先级
                    if is_dir:
                        file_type = 0
                    elif ext in VIDEO_EXTS:
                        file_type = 1
                    elif ext in IMAGE_EXTS:
                        file_type = 2
                    else:
                        file_type = 3

                    result = {
                        "name": name,
                        "path": rel_path.replace('\\', '/'),
                        "is_dir": is_dir,
                        "ext": ext,
                        "parent": os.path.dirname(rel_path).replace('\\', '/'),
                        "is_video": ext in VIDEO_EXTS,
                        "is_image": ext in IMAGE_EXTS,
                        "type": file_type,
                        "date": datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M'),
                        "timestamp": ctime,
                        "has_thumbnail": has_thumbnail,
                        "thumbnail": thumbnail
                    }
                    results.append(result)

        # 排序逻辑：先按类型，再按创建时间倒序
        results.sort(key=lambda x: (x['type'], -x['timestamp']))

        return jsonify({"results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/player')
def player():
    video_path = request.args.get('path')
    back_path = request.args.get('back', '/')
    video_name = os.path.basename(video_path)
    return render_template('player.html',
                           video_url=f"/stream/{video_path}",
                           video_name=video_name,
                           back_url=back_path)


# 异步生成缩略图接口
@app.route('/generate-thumbnail', methods=['POST'])
def api_generate_thumbnail():
    """前端触发的异步缩略图生成接口"""
    try:
        data = request.get_json()
        file_path = data.get('path')
        
        if not file_path:
            return jsonify({"error": "No file path provided"}), 400
        
        full_path = os.path.join(BASE_DIR, file_path)
        if not os.path.exists(full_path):
            return jsonify({"error": "File not found"}), 404
        
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in VIDEO_EXTS and ext not in IMAGE_EXTS:
            return jsonify({"error": "Unsupported file type"}), 400
        
        thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
        thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)
        
        # 如果已存在，直接返回成功
        if os.path.exists(thumbnail_path):
            return jsonify({"success": True, "thumbnail": f"/thumbnail/{thumbnail_name}"})
        
        # 生成缩略图
        if generate_thumbnail(full_path, thumbnail_path):
            return jsonify({"success": True, "thumbnail": f"/thumbnail/{thumbnail_name}"})
        else:
            return jsonify({"success": False, "error": "Failed to generate thumbnail"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
