# 1. 환경 설정
$RemoteUrl = "https://github.com/SeaLion-hub/DICEE.git"
$Branch = "js_0302"
$CurrentDir = Get-Location
$ParentDir = Split-Path -Path $CurrentDir -Parent
$TempDir = Join-Path -Path $ParentDir -ChildPath "DICEE_temp_sync"

Write-Host "--- 1. 원격 브랜치($Branch) 클론 시작 ---" -ForegroundColor Cyan
# 기존 임시 폴더가 있다면 삭제
if (Test-Path $TempDir) { 
    Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue 
}

# 원격 브랜치 클론
git clone --branch $Branch --single-branch $RemoteUrl $TempDir

if ($LASTEXITCODE -ne 0) {
    Write-Error "클론 실패. 브랜치 명이나 권한을 확인하세요."
    return
}

Write-Host "--- 2. 파일 복사 및 동기화 (로컬 -> 클론 폴더) ---" -ForegroundColor Cyan
# robocopy의 /MIR 옵션은 원본에 없는 파일을 대상에서 삭제하여 정확한 diff를 생성합니다.
# /XD .git 을 통해 로컬의 .git 설정 복사를 방지합니다.
robocopy $CurrentDir $TempDir /MIR /XD .git /R:3 /W:5 /NP /NDL /NFL

Write-Host "--- 3. 변경 사항 커밋 및 푸시 ---" -ForegroundColor Cyan
Push-Location $TempDir
git add -A
git commit -m "DICE 앱 코드 업데이트"

# --force 없이 푸시
git push origin $Branch

if ($LASTEXITCODE -eq 0) {
    Write-Host "--- 작업 완료! ---" -ForegroundColor Green
} else {
    Write-Host "--- 푸시 중 오류가 발생했습니다. ---" -ForegroundColor Red
}

Pop-Location
# 작업 완료 후 임시 폴더 삭제 (필요 시 주석 해제)
# Remove-Item -Recurse -Force $TempDir
