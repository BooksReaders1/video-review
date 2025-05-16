import os
import hashlib
from datetime import datetime
from flask import Flask, send_from_directory, jsonify, request, render_template
import ffmpeg

app = Flask(__name__)
BASE_DIR = "D:/BaiduNetdiskDownload/shixi/Tools/beifen"   # 替换为你的实际视频目录
THUMBNAIL_DIR = os.path.join(os.path.dirname(__file__), "thumbnails")
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# 支持的文件类型
VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.rmvb']
IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']


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

            # 初始化缩略图相关字段
            has_thumbnail = False
            thumbnail = ""

            if not is_dir and (ext in VIDEO_EXTS or ext in IMAGE_EXTS):
                thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
                thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)

                if not os.path.exists(thumbnail_path):
                    if generate_thumbnail(full_path, thumbnail_path):
                        has_thumbnail = True
                else:
                    has_thumbnail = True

                if has_thumbnail:
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


@app.route('/stream/<path:filename>')
def stream_file(filename):
    return send_from_directory(BASE_DIR, filename)

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

                    # 初始化缩略图相关字段
                    has_thumbnail = False
                    thumbnail = ""

                    if not is_dir and (ext in VIDEO_EXTS or ext in IMAGE_EXTS):
                        thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
                        thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)

                        if not os.path.exists(thumbnail_path):
                            if generate_thumbnail(full_path, thumbnail_path):
                                has_thumbnail = True
                        else:
                            has_thumbnail = True

                        if has_thumbnail:
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


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)