import os
import hashlib
from datetime import datetime
from flask import Flask, send_from_directory, jsonify, request
import subprocess

app = Flask(__name__)
BASE_DIR = "D:/BaiduNetdiskDownload/shixi/Tools/beifen"  # 替换为你的实际视频目录
THUMBNAIL_DIR = os.path.join(os.path.dirname(__file__), "thumbnails")
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# 支持的文件类型
VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv']
IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']


# 生成缩略图
def generate_thumbnail(file_path, thumbnail_path):
    try:
        if os.path.splitext(file_path)[1].lower() in VIDEO_EXTS:
            cmd = [
                'ffmpeg',
                '-i', file_path,
                '-ss', '00:00:01',
                '-vframes', '1',
                '-vf', 'scale=320:-1',
                '-y',
                thumbnail_path
            ]
        elif os.path.splitext(file_path)[1].lower() in IMAGE_EXTS:
            from PIL import Image
            img = Image.open(file_path)
            img.thumbnail((320, 320))
            img.save(thumbnail_path)
            return True
        else:
            return False

        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        print(f"生成缩略图失败: {str(e)}")
        return False


@app.route('/files/', defaults={'subpath': ''})
@app.route('/files/<path:subpath>')
def list_files(subpath):
    try:
        target_dir = os.path.join(BASE_DIR, subpath)

        # 获取排序参数
        sort_by = request.args.get('sort', 'type')  # 默认按类型排序
        order = request.args.get('order', 'desc' if sort_by == 'date' else 'asc')

        items = []
        for name in os.listdir(target_dir):
            full_path = os.path.join(target_dir, name)
            is_dir = os.path.isdir(full_path)
            ext = os.path.splitext(name)[1].lower()

            # 确定文件类型优先级
            if is_dir:
                file_type = 0  # 文件夹最高优先级
            elif ext in VIDEO_EXTS:
                file_type = 1  # 视频
            elif ext in IMAGE_EXTS:
                file_type = 2  # 图片
            else:
                file_type = 3  # 其他文件

            item = {
                "name": name,
                "path": os.path.join(subpath, name).replace('\\', '/'),
                "is_dir": is_dir,
                "ext": ext,
                "date": os.path.getmtime(full_path),
                "size": os.path.getsize(full_path) if not is_dir else 0,
                "type": file_type,
                "is_video": ext in VIDEO_EXTS,
                "is_image": ext in IMAGE_EXTS,
                "has_thumbnail": False
            }

            # 生成缩略图（视频和图片）
            if item['is_video'] or item['is_image']:
                thumbnail_name = f"{hashlib.md5(full_path.encode()).hexdigest()}.jpg"
                thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_name)

                if not os.path.exists(thumbnail_path):
                    if generate_thumbnail(full_path, thumbnail_path):
                        item['has_thumbnail'] = True
                else:
                    item['has_thumbnail'] = True

                item['thumbnail'] = f"/thumbnail/{thumbnail_name}" if item['has_thumbnail'] else ""

            items.append(item)

        # 排序逻辑：先按类型，再按时间倒序
        items.sort(key=lambda x: (
            x['type'],
            -x['date'] if sort_by == 'date' and order == 'desc' else x['date'],
            x['name'].lower()
        ))

        # 转换日期格式用于显示
        for item in items:
            item['date'] = datetime.fromtimestamp(item['date']).strftime('%Y-%m-%d %H:%M')

        return jsonify({
            "path": subpath,
            "items": items,
            "parent": os.path.dirname(subpath).replace('\\', '/') if subpath else None
        })

    except FileNotFoundError:
        return jsonify({"error": "Directory not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/thumbnail/<filename>')
def get_thumbnail(filename):
    return send_from_directory(THUMBNAIL_DIR, filename)


@app.route('/stream/<path:filename>')
def stream_file(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)