#!/usr/bin/env python3
"""
식품의약품안전처(MFDS) 의약품안전나라 웹사이트에서 첨부파일을 다운로드하는 스크립트

사용법:
    python mfds_downloader.py "https://nedrug.mfds.go.kr/CCBAR01F012/getList/getItem?infoNo=20240297&infoClassCode=4"
"""

import requests
import os
import sys
import re
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
import time
from pathlib import Path

class MFDSFileDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        })
        self.base_url = 'https://nedrug.mfds.go.kr'
    
    def get_page_content(self, url):
        """웹페이지 내용을 가져옵니다."""
        try:
            print("페이지 요청 중...")
            response = self.session.get(url)
            response.raise_for_status()
            response.encoding = 'utf-8'
            print(f"페이지 크기: {len(response.text)} 문자")
            return response.text
        except requests.RequestException as e:
            print(f"페이지를 가져오는 중 오류 발생: {e}")
            return None
    
    def extract_file_info(self, html_content):
        """HTML에서 첨부파일 정보를 추출합니다."""
        print("HTML 파싱 중...")
        soup = BeautifulSoup(html_content, 'html.parser')
        files = []
        
        # 실제 HTML 구조에 맞춰 수정: downEdmsFile 함수 찾기
        downedms_matches = re.findall(r"downEdmsFile\('([^']+)'\)", html_content)
        print(f"HTML에서 발견된 downEdmsFile 호출: {len(downedms_matches)}개")
        for match in downedms_matches:
            print(f"  - docId: {match}")
        
        # 첨부파일 테이블 찾기 (실제 HTML 구조 기반)
        # id="fileTableTr" 테이블 찾기
        file_table = soup.find('table', {'id': 'fileTableTr'})
        
        if file_table:
            print("✓ 첨부파일 테이블 발견 (id='fileTableTr')")
            rows = file_table.find('tbody').find_all('tr')
            print(f"테이블 행 수: {len(rows)}")
            
            for i, row in enumerate(rows):
                cells = row.find_all('td')
                if len(cells) >= 3:
                    # 순번, 파일명, 다운로드 버튼
                    seq_num = cells[0].get_text(strip=True)
                    filename = cells[1].get_text(strip=True)
                    download_cell = cells[2]
                    
                    # 다운로드 버튼에서 onclick 속성 찾기
                    download_btn = download_cell.find('button')
                    if download_btn:
                        onclick = download_btn.get('onclick', '')
                        print(f"행 {i+1}: {filename}")
                        print(f"  onclick: {onclick}")
                        
                        # downEdmsFile('docId') 패턴에서 docId 추출
                        doc_id_match = re.search(r"downEdmsFile\('([^']+)'\)", onclick)
                        if doc_id_match:
                            doc_id = doc_id_match.group(1)
                            files.append({
                                'filename': filename,
                                'doc_id': doc_id,
                                'seq_num': seq_num
                            })
                            print(f"  ✓ 추출 성공 - docId: {doc_id}")
                        else:
                            print(f"  ✗ docId 추출 실패")
        else:
            print("✗ 첨부파일 테이블을 찾을 수 없음")
            
            # 대안: 전체 HTML에서 downEdmsFile 패턴 찾기
            print("대안 방법: 전체 HTML에서 downEdmsFile 패턴 검색...")
            buttons = soup.find_all('button')
            
            for i, button in enumerate(buttons):
                onclick = button.get('onclick', '')
                if 'downEdmsFile' in onclick:
                    doc_id_match = re.search(r"downEdmsFile\('([^']+)'\)", onclick)
                    if doc_id_match:
                        doc_id = doc_id_match.group(1)
                        
                        # 파일명 찾기 - title 속성에서
                        title = button.get('title', '')
                        filename = title if title else f"첨부파일_{i+1}"
                        
                        # 또는 같은 행의 다른 셀에서 파일명 찾기
                        row = button.find_parent('tr')
                        if row and not title:
                            cells = row.find_all('td')
                            if len(cells) >= 2:
                                filename = cells[1].get_text(strip=True)
                        
                        files.append({
                            'filename': filename,
                            'doc_id': doc_id,
                            'seq_num': str(i+1)
                        })
                        print(f"  ✓ 버튼에서 추출: {filename} - {doc_id}")
        
        print(f"최종 추출된 파일 수: {len(files)}")
        return files
    
    def download_file(self, doc_id, filename, download_dir='downloads'):
        """파일을 다운로드합니다."""
        try:
            # 다운로드 디렉토리 생성
            Path(download_dir).mkdir(exist_ok=True)
            
            print(f"파일 다운로드 시작: {doc_id}")
            # 실제 파일 다운로드 (파일 존재 확인 단계 생략)
            download_url = f"{self.base_url}/cmn/edms/down/{doc_id}"
            
            response = self.session.get(download_url, stream=True)
            response.raise_for_status()
            
            # Content-Disposition 헤더에서 실제 파일명 추출 시도
            content_disposition = response.headers.get('Content-Disposition', '')
            print(f"Content-Disposition: {content_disposition}")
            
            actual_filename = filename
            if 'filename=' in content_disposition:
                try:
                    filename_match = re.search(r'filename[*]?=["\']?([^"\';\r\n]*)', content_disposition)
                    if filename_match:
                        actual_filename = unquote(filename_match.group(1))
                        print(f"헤더에서 추출한 파일명: {actual_filename}")
                except:
                    pass
            
            # 파일명 정리 (안전한 파일명으로 변경)
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', actual_filename)
            if not safe_filename.strip():
                safe_filename = f"download_{doc_id}"
                content_type = response.headers.get('Content-Type', '').lower()
                if 'pdf' in content_type:
                    safe_filename += '.pdf'
                elif 'zip' in content_type:
                    safe_filename += '.zip'
                elif 'excel' in content_type or 'spreadsheet' in content_type:
                    safe_filename += '.xlsx'
            
            file_path = os.path.join(download_dir, safe_filename)
            
            # 파일 저장
            print(f"파일 저장 중: {file_path}")
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            file_size = os.path.getsize(file_path)
            print(f"다운로드 완료: {file_path} ({file_size} bytes)")
            return True
            
        except requests.RequestException as e:
            print(f"파일 다운로드 중 네트워크 오류 ({filename}): {e}")
            return False
        except Exception as e:
            print(f"파일 저장 중 오류 발생 ({filename}): {e}")
            return False
    
    def download_attachments_from_url(self, url, download_dir='downloads'):
        """주어진 URL에서 모든 첨부파일을 다운로드합니다."""
        print(f"페이지 분석 중: {url}")
        
        # 페이지 내용 가져오기
        html_content = self.get_page_content(url)
        if not html_content:
            return False
        
        # 첨부파일 정보 추출
        files = self.extract_file_info(html_content)
        
        if not files:
            print("첨부파일을 찾을 수 없습니다.")
            print("\n디버깅을 위해 주요 부분을 확인해보세요:")
            
            # downEdmsFile 패턴 검색
            downedms_pattern = re.findall(r"downEdmsFile\([^)]+\)", html_content)
            if downedms_pattern:
                print("=== 발견된 downEdmsFile 패턴 ===")
                for pattern in downedms_pattern[:5]:  # 처음 5개만 출력
                    print(f"  {pattern}")
            
            # 첨부파일 관련 테이블 확인
            soup = BeautifulSoup(html_content, 'html.parser')
            tables_with_file = soup.find_all('table', string=re.compile('첨부파일|다운로드'))
            if tables_with_file:
                print("=== 첨부파일 관련 테이블 발견 ===")
                for table in tables_with_file[:2]:  # 처음 2개만
                    print(f"  테이블 id: {table.get('id', '없음')}")
                    print(f"  테이블 class: {table.get('class', '없음')}")
            
            return False
        
        print(f"발견된 첨부파일: {len(files)}개")
        for i, file_info in enumerate(files, 1):
            print(f"  {i}. {file_info['filename']} (docId: {file_info['doc_id']})")
        
        # 각 파일 다운로드
        success_count = 0
        for i, file_info in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] 다운로드 중: {file_info['filename']}")
            
            if self.download_file(file_info['doc_id'], file_info['filename'], download_dir):
                success_count += 1
            
            # 서버 부하 방지를 위한 대기
            time.sleep(1)
        
        print(f"\n다운로드 완료: {success_count}/{len(files)} 파일")
        return success_count > 0

def main():
    """메인 함수"""
    if len(sys.argv) != 2:
        print("사용법: python mfds_downloader.py <URL>")
        print("예시: python mfds_downloader.py 'https://nedrug.mfds.go.kr/CCBAR01F012/getList/getItem?infoNo=20240297&infoClassCode=4'")
        sys.exit(1)
    
    url = sys.argv[1]
    downloader = MFDSFileDownloader()
    
    try:
        success = downloader.download_attachments_from_url(url)
        if success:
            print("\n모든 작업이 완료되었습니다!")
        else:
            print("\n다운로드 중 문제가 발생했습니다.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n예상치 못한 오류가 발생했습니다: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# JavaScript downEdmsFile 함수를 위한 추가 함수 (참고용)
def create_js_downloader():
    """
    웹페이지에서 사용하는 JavaScript 함수를 참고하여 
    실제 다운로드 로직을 구현하는 방법
    """
    js_code = """
    // 원본 JavaScript 함수 (참고용)
    function downEdmsFile(docId) {
        var url = '/cmn/edms/down/' + docId;
        window.location.href = url;
    }
    """
    print("참고: 웹페이지의 JavaScript 다운로드 함수")
    print(js_code)

if __name__ == "__main__":
    main()