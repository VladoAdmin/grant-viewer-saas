<?php
/**
 * API Proxy for Grant Viewer.
 * Forwards requests from stormlevel.com to the Tailscale backend.
 * Solves Chrome's Private Network Access (PNA) blocking.
 */

// Backend URL
$BACKEND = 'https://srv1319479.tailcd1c2c.ts.net/grant-viewer-api';

// CORS headers
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

// Handle preflight
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// Get the path after proxy.php
$path = isset($_SERVER['PATH_INFO']) ? $_SERVER['PATH_INFO'] : '';
if (empty($path) && isset($_SERVER['QUERY_STRING'])) {
    // Fallback: check for ?path= parameter
    parse_str($_SERVER['QUERY_STRING'], $qs);
    if (isset($qs['_path'])) {
        $path = '/' . ltrim($qs['_path'], '/');
        unset($qs['_path']);
        $_SERVER['QUERY_STRING'] = http_build_query($qs);
    }
}

// Build target URL
$targetUrl = $BACKEND . $path;
$queryString = $_SERVER['QUERY_STRING'] ?? '';
if (!empty($queryString)) {
    $targetUrl .= '?' . $queryString;
}

// Prepare cURL
$ch = curl_init($targetUrl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 120);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);

// Forward method
$method = $_SERVER['REQUEST_METHOD'];
if ($method === 'POST') {
    $body = file_get_contents('php://input');
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
} elseif ($method === 'PUT') {
    $body = file_get_contents('php://input');
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'PUT');
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
} elseif ($method === 'DELETE') {
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, 'DELETE');
}

// Forward Content-Type
$contentType = $_SERVER['HTTP_CONTENT_TYPE'] ?? 'application/json';
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    'Content-Type: ' . $contentType,
]);

// Capture response headers
$responseHeaders = [];
curl_setopt($ch, CURLOPT_HEADERFUNCTION, function($ch, $header) use (&$responseHeaders) {
    $len = strlen($header);
    $parts = explode(':', $header, 2);
    if (count($parts) === 2) {
        $name = strtolower(trim($parts[0]));
        // Skip hop-by-hop and CORS headers (we set our own)
        if (!in_array($name, ['transfer-encoding', 'connection', 'access-control-allow-origin',
            'access-control-allow-methods', 'access-control-allow-headers'])) {
            $responseHeaders[$name] = trim($parts[1]);
        }
    }
    return $len;
});

// Execute
$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$error = curl_error($ch);
curl_close($ch);

if ($error) {
    http_response_code(502);
    header('Content-Type: application/json');
    echo json_encode(['error' => 'Proxy error', 'message' => $error]);
    exit;
}

// Forward response
http_response_code($httpCode);
if (isset($responseHeaders['content-type'])) {
    header('Content-Type: ' . $responseHeaders['content-type']);
} else {
    header('Content-Type: application/json');
}
echo $response;
