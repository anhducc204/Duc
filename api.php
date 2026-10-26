<?php
// Local XAMPP bridge. The Python worker must be started with start.bat.
declare(strict_types=1);
$action = $_GET['action'] ?? 'config';
if (!preg_match('~^(config|jobs|analyze|download|cancel|remove|file/[a-f0-9]{32})$~D', $action)) {
    http_response_code(400);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'Thao tác không hợp lệ.']);
    exit;
}
$remote = $_SERVER['REMOTE_ADDR'] ?? '';
$hostname = parse_url('http://' . ($_SERVER['HTTP_HOST'] ?? ''), PHP_URL_HOST);
if (!in_array($remote, ['127.0.0.1', '::1'], true) || !in_array($hostname, ['localhost', '127.0.0.1', '::1', '[::1]'], true)) {
    http_response_code(403);
    exit('Local access only');
}
$headers = ['Content-Type: application/json'];
if (isset($_SERVER['HTTP_X_DOWNVIDEO_TOKEN'])) $headers[] = 'X-DownVideo-Token: ' . $_SERVER['HTTP_X_DOWNVIDEO_TOKEN'];
if (isset($_SERVER['HTTP_ORIGIN'])) $headers[] = 'Origin: ' . $_SERVER['HTTP_ORIGIN'];
if (isset($_SERVER['HTTP_RANGE'])) $headers[] = 'Range: ' . $_SERVER['HTTP_RANGE'];
$context = stream_context_create(['http' => [
    'method' => $_SERVER['REQUEST_METHOD'],
    'header' => implode("\r\n", $headers),
    'content' => file_get_contents('php://input'),
    'timeout' => 60, 'ignore_errors' => true,
]]);
$stream = @fopen('http://127.0.0.1:8765/api/' . $action, 'rb', false, $context);
if ($stream === false) {
    http_response_code(503);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => 'Máy chủ tải chưa chạy. Hãy mở start.bat trong thư mục DownVideo.'], JSON_UNESCAPED_UNICODE);
    exit;
}
foreach ($http_response_header ?? [] as $header) {
    if (preg_match('~^HTTP/\S+ (\d+)~', $header, $match)) http_response_code((int)$match[1]);
    elseif (preg_match('~^(Content-Type|Content-Length|Content-Disposition|Content-Range|Accept-Ranges|Cache-Control|X-Content-Type-Options):~i', $header)) header($header);
}
while (!feof($stream)) {
    echo fread($stream, 1024 * 1024);
    flush();
}
fclose($stream);

