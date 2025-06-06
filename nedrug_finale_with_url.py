import os
import time
import re
import requests
import fitz  # PyMuPDF (for PDF text extraction)
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from PyPDF2 import PdfReader, errors
from datetime import datetime
import xlsxwriter # xlsxwriter 추가

# --- 설정 ---
BASE_URL = "https://nedrug.mfds.go.kr/CCBAR01F012/getList"

# 현재 Python 스크립트 파일이 위치한 디렉토리를 기본 저장 디렉토리로 설정
SCRIPT_RUN_DIR = os.path.dirname(os.path.abspath(__file__))

# 결과 디렉토리 이름을 'nedrug_년도_월일_시간_분' 형식으로 구성
now = datetime.now()
RESULT_FOLDER_NAME = now.strftime("nedrug_%Y%m%d_%H%M")

# 최종 결과물 (엑셀)이 저장될 디렉토리
EXCEL_SAVE_DIR = os.path.join(SCRIPT_RUN_DIR, RESULT_FOLDER_NAME)

# PDF 파일이 저장될 디렉토리 (이제 PDF만 다운로드하므로 이름 변경 불필요)
DOWNLOAD_DIR = os.path.join(EXCEL_SAVE_DIR, "nedrug_pdfs")

# 필요한 디렉토리 생성
os.makedirs(EXCEL_SAVE_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

print(f"📁 저장 경로 설정:")
print(f"   스크립트 실행 폴더: {SCRIPT_RUN_DIR}")
print(f"   결과 저장 폴더: {EXCEL_SAVE_DIR}")
print(f"   PDF 저장 폴더: {DOWNLOAD_DIR}")

# --- 크롬 설정 ---
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")

# --- User-Agent 및 재시도 설정 ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
MAX_RETRIES = 3
RETRY_DELAY = 2 # 초

# --- 유틸리티 함수 정의 (중복 제거 및 가독성 향상) ---

def _extract_text_from_pdf_with_fitz(pdf_path):
    """PyMuPDF(fitz)를 사용하여 PDF에서 텍스트 추출"""
    try:
        doc = fitz.open(pdf_path)
        full_text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return full_text if full_text.strip() else ""
    except Exception as e:
        print(f"        ⚠️  PyMuPDF로 PDF 텍스트 추출 실패: {e}")
        return ""

def _extract_text_from_pdf_with_pypdf2(pdf_path):
    """PyPDF2를 사용하여 PDF에서 텍스트 추출"""
    try:
        reader = PdfReader(pdf_path)
        full_text = "\n".join(page.extract_text() for page in reader.pages)
        return full_text if full_text.strip() else ""
    except (errors.PdfReadError, Exception) as e: # PDF Read Error 및 기타 예외 처리
        print(f"        ⚠️  PyPDF2로 PDF 텍스트 추출 실패: {e}")
        return ""

def _extract_date_with_patterns(text, patterns, source_name=""):
    """주어진 텍스트에서 패턴 리스트를 사용하여 날짜 추출"""
    for i, pattern in enumerate(patterns, 1):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) >= 3:
                y, m, d = groups[:3]
                try:
                    formatted_date = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                    return formatted_date, match.group(), f"(패턴 {i})"
                except ValueError:
                    # print(f"        ⚠️  {source_name} 패턴 {i} 일치했으나 날짜 변환 실패: {groups}")
                    continue
    return "", "", ""


# --- 기존 함수들 (일부 수정) ---

def get_total_pages(driver):
    """총 페이지 수를 확인하는 함수"""
    try:
        last_page_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[title*='마지막']"))
        )
        last_page_btn.click()
        time.sleep(2)
       
        current_url = driver.current_url
        total_pages = 1
        total_items = 0
       
        if "totalPages=" in current_url:
            total_pages = int(re.search(r'totalPages=(\d+)', current_url).group(1))
            print(f"✅ 총 페이지 수: {total_pages}")
           
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            last_page_items = len(rows)
            total_items = (total_pages - 1) * 10 + last_page_items
            print(f"✅ 총 항목 수: {total_items}건")
           
        else:
            page_links = driver.find_elements(By.CSS_SELECTOR, "div.pagination a")
            if page_links:
                total_pages = int(page_links[-1].text.strip())
                total_items = total_pages * 10
                print(f"✅ 총 페이지 수: {total_pages} (추정 항목 수: {total_items}건)")
       
        return total_pages, total_items
       
    except Exception as e:
        print(f"⚠️  총 페이지 수 확인 실패: {e}")
        return 1, 10

def navigate_to_page(driver, page_num):
    """특정 페이지로 이동하는 함수"""
    try:
        page_url = f"{BASE_URL}?page={page_num}&limit=10"
        driver.get(page_url)
       
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
        time.sleep(1)
        return True
    except TimeoutException:
        print(f"⚠️  페이지 {page_num} 로딩 실패")
        return False

def extract_ingredient_name_from_html(driver):
    """HTML 페이지에서 성분정보 테이블의 원료/성분명(영문) 추출"""
    try:
        ingredient_table = driver.find_elements(By.XPATH, "//p[contains(@class, 'cont_title3') and contains(text(), '성분정보')]/following-sibling::div//table")
        if not ingredient_table:
            return ""
        try:
            english_name_cell = ingredient_table[0].find_element(By.XPATH, ".//tbody/tr[1]/td[3]")
            ingredient_name = english_name_cell.text.strip()
            return ingredient_name if ingredient_name else ""
        except Exception:
            return ""
    except Exception:
        return ""

def extract_submit_deadline_from_html(driver):
    """HTML 페이지에서 의견제출기한 추출"""
    try:
        deadline_cell = driver.find_elements(By.XPATH, "//th[contains(text(), '의견제출기한')]/following-sibling::td")
        if deadline_cell:
            deadline_text = deadline_cell[0].text.strip()
            return deadline_text if re.match(r'\d{4}-\d{2}-\d{2}', deadline_text) else ""
        else:
            return ""
    except Exception:
        return ""

def extract_plan_date_from_html(driver):
    """HTML 페이지에서 허가사항 변경명령 예정일 추출"""
    try:
        content_textarea = driver.find_elements(By.XPATH, "//th[contains(text(), '내용')]/following-sibling::td//textarea")
        if content_textarea:
            content_text = content_textarea[0].text.strip()
            plan_patterns = [
                r"허가사항\s*변경\s*명령\s*예정일\s*[:：]\s*(\d{4})\.(\d{1,2})\.(\d{1,2})",
                r"변경\s*명령\s*예정일\s*[:：]\s*(\d{4})\.(\d{1,2})\.(\d{1,2})",
                r"예정일\s*[:：]\s*(\d{4})\.(\d{1,2})\.(\d{1,2})",
                r"○\s*허가사항\s*변경\s*명령\s*예정일\s*[:：]\s*(\d{4})\.(\d{1,2})\.(\d{1,2})",
            ]
            for pattern in plan_patterns:
                plan_match = re.search(pattern, content_text, re.IGNORECASE)
                if plan_match:
                    y, m, d = plan_match.groups()
                    return f"{y}-{int(m):02d}-{int(d):02d}"
            return ""
        else:
            return ""
    except Exception:
        return ""

def extract_reflect_date_from_html(driver):
    """HTML 페이지에서 허가반영일자 추출"""
    try:
        reflect_cell = driver.find_elements(By.XPATH, "//th[contains(text(), '허가반영일자')]/following-sibling::td")
        if reflect_cell:
            reflect_text = reflect_cell[0].text.strip()
            return reflect_text if re.match(r'\d{4}-\d{2}-\d{2}', reflect_text) else ""
        else:
            return ""
    except Exception:
        return ""

def extract_ingredient_name_from_pdf(full_text):
    """PDF에서 원료/성분명(영문) 추출 함수 (HTML 추출 실패시 백업용)"""
    try:
        patterns = [
            r"알림\(([A-Za-z\s]+)\s*성분\s*제제\)",
            r"예고\s*알림\(([A-Za-z\s]+)\s*성분\s*제제\)",
            r"의견조회\(([A-Za-z\s]+)\s*성분\s*제제\)",
            r"제목[^)]*\(([A-Za-z\s]+)\s*성분\s*제제\)",
            r"'([A-Za-z][A-Za-z\s]*[A-Za-z])'\s*성분",
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        ]
        for i, pattern in enumerate(patterns, 1):
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                ingredient = match.group(1).strip()
                ingredient = re.sub(r'\s+', ' ', ingredient)
                if len(ingredient) > 2 and any(c.isalpha() for c in ingredient):
                    print(f"    ✅ PDF에서 원료/성분명 추출 성공 (패턴 {i}): {ingredient}")
                    return ingredient
        return ""
    except Exception as e:
        print(f"    ⚠️  PDF에서 원료/성분명 추출 실패: {e}")
        return ""

def extract_exec_date_from_pdf(pdf_path):
    """
    PDF에서 '시행' 날짜를 추출하는 함수.
    PyMuPDF (fitz)와 PyPDF2를 모두 사용하여 추출 성공률을 높입니다.
    """
    exec_date = ""
    full_text_fitz = ""

    print(f"        🔎 extract_exec_date_from_pdf 호출: {os.path.basename(pdf_path)}")
    
    # 1. PyMuPDF (fitz)를 이용한 텍스트 추출 시도
    full_text_fitz = _extract_text_from_pdf_with_fitz(pdf_path)
    if full_text_fitz:
        print(f"        ✅ PyMuPDF 텍스트 추출 성공. 길이: {len(full_text_fitz)}")
    else:
        print(f"        ⚠️  PyMuPDF 텍스트가 비어있음 - PyPDF2 시도")

    # 2. PyMuPDF로 추출된 텍스트에서 날짜 패턴 검색
    if full_text_fitz:
        search_text = full_text_fitz
        print(f"        🔍 PyMuPDF 텍스트 전체 검색 시작 (길이: {len(search_text)})")

        exec_patterns = [
            r"시행\s*\((\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\)",
            r"시행\s+[^)]*\s*\((\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\)",
            r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\)\s*시행",
            r"시행일\s*[:：]?\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
            r"시행\s*[:：]?\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
            r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*시행",
            r"시행\s*[:：]?\s*(\d{4})[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})",
            r"(\d{4})[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})\s*시행",
            r"시행\s*[^0-9]*(\d{4})\.(\d{1,2})\.(\d{1,2})\.",
            r"시행일자\s*(\d{4})-(\d{1,2})-(\d{1,2})",
            r"시행[^:]*:\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
            r"(\d{4})\s*.\s*(\d{1,2})\s*.\s*(\d{1,2})\s*.\s*\(시행\)",
            r"\((\d{4})\s*.\s*(\d{1,2})\s*.\s*(\d{1,2})\s*.\)\s*시행",
        ]
        
        exec_date, matched_text, pattern_info = _extract_date_with_patterns(search_text, exec_patterns, "PyMuPDF 텍스트")
        if exec_date:
            print(f"        ✅ PyMuPDF 텍스트에서 시행날짜 추출 성공 {pattern_info}: {exec_date} (매치: '{matched_text}')")
            return exec_date
        else:
            print(f"        ❌ PyMuPDF 텍스트에서 시행날짜 패턴을 찾지 못함. 텍스트 샘플 (마지막 500자):\n{search_text[-500:]}...")
            for match_obj in re.finditer(r"시행.{0,100}(?:\d{4}[년.\-]\d{1,2}[월.\-]\d{1,2}[일.]?)", search_text, re.IGNORECASE):
                print(f"            👉 '시행' 주변에서 날짜와 함께 발견된 텍스트: {match_obj.group()}")

    # 3. PyMuPDF에서 텍스트 추출에 실패했거나, 패턴을 찾지 못했다면 PyPDF2 시도
    if not exec_date:
        print(f"        🔍 PyPDF2로 시행날짜 추출 시도...")
        text_pypdf2 = _extract_text_from_pdf_with_pypdf2(pdf_path)
        if text_pypdf2:
            print(f"        ✅ PyPDF2 텍스트 추출 성공. 길이: {len(text_pypdf2)}")
            # PyPDF2 전용 패턴 (괄호 안의 날짜가 잘 잡힘)
            date_pattern_pypdf2_specific = r"\((20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\)"
            
            # '시행'이 있는 줄에서 PyMuPDF의 모든 패턴 + PyPDF2 전용 패턴 시도
            all_pypdf2_patterns = exec_patterns + [date_pattern_pypdf2_specific]
            
            # PyPDF2는 줄 단위로 처리하는 것이 효율적이므로, 줄별 검색 유지
            for line in text_pypdf2.splitlines():
                if "시행" in line:
                    print(f"            🔎 PyPDF2 '시행' 발견 줄: '{line.strip()}'")
                    exec_date, matched_text, pattern_info = _extract_date_with_patterns(line, all_pypdf2_patterns, "PyPDF2 줄 텍스트")
                    if exec_date:
                        print(f"            ✅ PyPDF2로 시행날짜 추출 성공 {pattern_info}: {exec_date} (매치: '{matched_text}')")
                        return exec_date
                    else:
                        print(f"            ❌ PyPDF2: '시행'이 있는 줄에서 날짜 패턴을 찾지 못함 (줄: '{line.strip()}')")
            print(f"        ❌ PyPDF2에서도 시행 날짜를 찾지 못했습니다. (모든 페이지 검색 완료)")
        else:
            print(f"        ⚠️  PyPDF2 텍스트도 비어있음.")

    return exec_date


def extract_submit_deadline_from_pdf(full_text):
    """PDF 텍스트에서 의견제출기한 추출"""
    patterns = [
        r"의견제출기한\s*[:：]?\s*(\d{4})[.\-년\s]*(\d{1,2})[.\-월\s]*(\d{1,2})[일\s]*",
        r"기한\s*:\s*(\d{4})[.\- ]*(\d{1,2})[.\- ]*(\d{1,2})",
        r"의견수렴기간\s*:\s*(\d{4})[.\- ]*(\d{1,2})[.\- ]*(\d{1,2})\s*~",
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일까지",
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*까지"
    ]
    for i, pattern in enumerate(patterns, 1):
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            y, m, d = match.groups()[:3]
            formatted_date = f"{y}-{int(m):02d}-{int(d):02d}"
            return formatted_date
    return ""

def extract_plan_date_from_pdf(full_text):
    """PDF 텍스트에서 허가사항 변경명령 예정일 추출"""
    patterns = [
        r"허가사항\s*변경\s*명령\s*예정일\s*[:：]?\s*(\d{4})[.\-년\s]*(\d{1,2})[.\-월\s]*(\d{1,2})[일\s]*",
        r"변경\s*명령\s*예정일\s*[:：]?\s*(\d{4})[.\-년\s]*(\d{1,2})[.\-월\s]*(\d{1,2})[일\s]*",
        r"예정일\s*[:：]?\s*(\d{4})[.\-년\s]*(\d{1,2})[.\-월\s]*(\d{1,2})[일\s]*",
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*부터\s*시행\s*예정",
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*시행\s*예정"
    ]
    for i, pattern in enumerate(patterns, 1):
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            y, m, d = match.groups()[:3]
            formatted_date = f"{y}-{int(m):02d}-{int(d):02d}"
            return formatted_date
    return ""

def extract_reflect_date_from_pdf(full_text):
    """PDF 텍스트에서 허가반영일자 추출"""
    patterns = [
        r"허가반영일자\s*[:：]?\s*(\d{4})[.\-년\s]*(\d{1,2})[.\-월\s]*(\d{1,2})[일\s]*",
        r"반영일자\s*[:：]?\s*(\d{4})[.\-년\s]*(\d{1,2})[.\-월\s]*(\d{1,2})[일\s]*",
        r"변경\s*반영일자\s*:\s*(\d{4})\s*(\d{1,2})\s*(\d{1,2})",
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*변경\s*반영",
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*일\s*변경\s*반영"
    ]
    for i, pattern in enumerate(patterns, 1):
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            y, m, d = match.groups()[:3]
            formatted_date = f"{y}-{int(m):02d}-{int(d):02d}"
            return formatted_date
    return ""

def process_single_item(driver, row, idx, downloaded_files, records):
    """개별 항목을 처리하는 함수"""
    current_item_processed_pdf_path = "" # 현재 항목에서 추출에 성공한 PDF의 경로 (하나만 필요)
    
    try:
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            return
           
        status = cells[5].text.strip()
        title_elem = cells[1].find_element(By.TAG_NAME, "a")
        title = title_elem.text.strip()
        href = title_elem.get_attribute("href")
        change_reflect_date = cells[4].text.strip() if len(cells) > 4 else ""

        print(f"[{idx}] 처리 중: {title} - {status}")

        if status not in ["변경명령(안) 의견조회", "사전예고", "변경명령"]:
            print(f"    ⏭️  스킵 (상태: {status})")
            return

        # 관련 URL 저장
        record_url = href

        driver.execute_script("window.open(arguments[0]);", href)
        driver.switch_to.window(driver.window_handles[-1])

        try:
            ingredient_name = extract_ingredient_name_from_html(driver)
            submit_deadline_from_html = ""
            plan_date_from_html = ""
            reflect_date_from_html = ""
           
            if status == "변경명령(안) 의견조회":
                submit_deadline_from_html = extract_submit_deadline_from_html(driver)
            elif status == "사전예고":
                plan_date_from_html = extract_plan_date_from_html(driver)
            elif status == "변경명령":
                reflect_date_from_html = extract_reflect_date_from_html(driver)
           
            need_pdf_processing = False
            # HTML에서 정보를 충분히 얻지 못했거나 시행날짜 추출이 필요한 경우 PDF 처리 시도
            if not ingredient_name or \
               (status == "변경명령(안) 의견조회" and not submit_deadline_from_html) or \
               (status == "사전예고" and not plan_date_from_html) or \
               (status == "변경명령" and not reflect_date_from_html) or \
               status in ["변경명령(안) 의견조회", "변경명령"]: # 시행날짜는 PDF에서만 추출
                need_pdf_processing = True
           
            if not need_pdf_processing:
                print(f"    🚀 HTML에서 모든 정보 추출 완료, PDF 다운로드 및 처리 생략")
            else:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button[onclick^='downEdmsFile']"))
                    )
                    buttons = driver.find_elements(By.CSS_SELECTOR, "button[onclick^='downEdmsFile']")
                except TimeoutException:
                    print(f"    ⚠️  첨부파일 버튼을 찾을 수 없음. PDF 처리 불가.")
                    buttons = []

                for btn in buttons:
                    file_id = ""
                    filename = ""
                    
                    try:
                        onclick = btn.get_attribute("onclick")
                        if not onclick:
                            continue
                           
                        file_id_match = re.search(r"downEdmsFile\('([^']+)',\s*'([^']+)'\)", onclick)
                        if not file_id_match:
                            file_id_match = re.search(r"downEdmsFile\('([^']+)'\)", onclick)
                            if file_id_match:
                                file_id = file_id_match.group(1)
                                filename = btn.get_attribute("title")
                                if not filename:
                                    filename = f"file_{file_id}.pdf" # 확장자가 없으면 일단 PDF로 가정
                            else:
                                continue
                        else:
                            file_id = file_id_match.group(1)
                            filename = file_id_match.group(2)

                        filename = filename.strip()
                        file_extension = os.path.splitext(filename)[1].lower()

                        # --- 최적화 1: PDF 파일만 다운로드 ---
                        if file_extension != '.pdf':
                            print(f"    ⏭️  PDF 파일 아님 ({file_extension}), 다운로드 스킵: {filename}")
                            continue

                        if filename in downloaded_files:
                            print(f"    ⏭️  이미 다운로드됨: {filename}")
                            continue

                        download_url = f"https://nedrug.mfds.go.kr/cmn/edms/down/{file_id}"
                        safe_filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
                        # 공백을 밑줄로 대체
                        safe_filename = safe_filename.replace(" ", "_")
                        local_file_path = os.path.join(DOWNLOAD_DIR, safe_filename)

                        file_content = None
                        for attempt in range(MAX_RETRIES):
                            try:
                                print(f"    ⏳ {filename} 다운로드 시도 {attempt + 1}/{MAX_RETRIES}...")
                                response = requests.get(download_url, headers=HEADERS, timeout=30)
                                response.raise_for_status()
                                file_content = response.content
                                print(f"      ✅ 다운로드 성공. 크기: {len(file_content)} bytes.")
                                break
                            except requests.exceptions.RequestException as req_err:
                                print(f"      ⚠️  다운로드 요청 실패 (재시도 {attempt + 1}): {req_err}")
                                time.sleep(RETRY_DELAY)
                            except Exception as general_err:
                                print(f"      ⚠️  다운로드 중 일반 오류 (재시도 {attempt + 1}): {general_err}")
                                time.sleep(RETRY_DELAY)
                        
                        if file_content is None:
                            print(f"   ❌ {filename} 모든 재시도 실패. 다운로드 건너뜜.")
                            continue

                        try:
                            with open(local_file_path, "wb") as f:
                                f.write(file_content)
                            print(f"   💾 파일 저장 완료: {safe_filename}")
                            downloaded_files.add(filename) # 성공적으로 다운로드된 파일만 set에 추가
                            current_item_processed_pdf_path = local_file_path # 이 항목에서 처리할 PDF 경로 저장 (첫 번째 성공한 PDF)
                            break # 첫 번째 PDF만 다운로드 성공하면 다음 PDF는 스킵 (최적화)
                            
                        except Exception as save_err:
                            print(f"   ❌ {filename} 저장 중 오류 발생: {save_err}")
                            continue

                    except Exception as btn_proc_error:
                        print(f"    ⚠️  버튼({filename}) 처리 중 오류 발생: {btn_proc_error}")
                        continue
            
            # --- 다운로드된 PDF 파일 (혹은 HTML에서 추출된 텍스트)에서 정보 추출 ---
            # 한 번 찾은 시행날짜, 제출날짜, 예정일, 반영일자는 덮어쓰지 않도록 플래그 사용
            record_exec_date = ""
            final_submit_deadline = ""
            final_plan_date = ""
            final_reflect_date = ""
            full_text_from_pdf = "" # 텍스트 추출은 여기서 한번만 수행
            record_pdf_path = "" # 관련 PDF 경로 저장

            # PDF가 성공적으로 다운로드되고 저장되었다면 텍스트 추출 시도
            if current_item_processed_pdf_path:
                print(f"    🔍 PDF 텍스트 추출 시작: {os.path.basename(current_item_processed_pdf_path)}")
                full_text_from_pdf = _extract_text_from_pdf_with_fitz(current_item_processed_pdf_path)
                if not full_text_from_pdf: # fitz 실패 시 PyPDF2 시도
                    full_text_from_pdf = _extract_text_from_pdf_with_pypdf2(current_item_processed_pdf_path)
                    if not full_text_from_pdf:
                        print(f"    ❌ {os.path.basename(current_item_processed_pdf_path)}에서 텍스트 추출 최종 실패.")
                # PDF 텍스트 추출 성공 여부와 관계없이, 다운로드된 PDF 경로를 저장합니다.
                record_pdf_path = current_item_processed_pdf_path
            
            # HTML에서 성분명 추출이 실패했다면 PDF 텍스트에서 추출 시도
            if not ingredient_name and full_text_from_pdf:
                ingredient_name = extract_ingredient_name_from_pdf(full_text_from_pdf)
                if ingredient_name:
                    print(f"    ✅ 최종 원료/성분명 (PDF에서 추출): {ingredient_name}")

            # 시행날짜 추출 (아직 찾지 못했을 경우에만 시도)
            if status in ["변경명령(안) 의견조회", "변경명령"] and not record_exec_date and full_text_from_pdf:
                exec_date_found = extract_exec_date_from_pdf(current_item_processed_pdf_path) # 함수 인자 변경 (텍스트 추출은 extract_exec_date_from_pdf 내부에서 수행)
                if exec_date_found:
                    record_exec_date = exec_date_found
                    print(f"    ✅ 시행날짜 추출 성공: {record_exec_date}")
                else:
                    print(f"    ❌ {os.path.basename(current_item_processed_pdf_path)} PDF에서 시행날짜 찾기 실패.")
            
            # 제출날짜/예정일/반영일자 추출 (아직 찾지 못했고, 텍스트가 있다면)
            if status == "변경명령(안) 의견조회" and not submit_deadline_from_html and not final_submit_deadline and full_text_from_pdf:
                extracted_date = extract_submit_deadline_from_pdf(full_text_from_pdf)
                if extracted_date:
                    final_submit_deadline = extracted_date
                    print(f"    ✅ 제출날짜 (PDF에서 추출): {final_submit_deadline}")

            if status == "사전예고" and not plan_date_from_html and not final_plan_date and full_text_from_pdf:
                extracted_date = extract_plan_date_from_pdf(full_text_from_pdf)
                if extracted_date:
                    final_plan_date = extracted_date
                    print(f"    ✅ 예정일 (PDF에서 추출): {final_plan_date}")

            if status == "변경명령" and not reflect_date_from_html and not final_reflect_date and full_text_from_pdf:
                extracted_date = extract_reflect_date_from_pdf(full_text_from_pdf)
                if extracted_date:
                    final_reflect_date = extracted_date
                    print(f"    ✅ 반영일자 (PDF에서 추출): {final_reflect_date}")

            # 최종 성분명 확인 (HTML 또는 PDF에서 추출된 것 중 마지막으로 업데이트된 값)
            if not ingredient_name:
                print(f"    ❌ 원료/성분명 추출 실패 (HTML 및 모든 PDF)")
                ingredient_name = ""

            final_exec_date = record_exec_date if record_exec_date else ""

            # 단계별로 다른 레코드 구조 생성
            if status == "변경명령(안) 의견조회":
                record = {
                    "A_제목": title,
                    "B_단계": "의견조회",
                    "C_시행날짜": final_exec_date,
                    "D_제출날짜": submit_deadline_from_html if submit_deadline_from_html else final_submit_deadline,
                    "E_예정일": "",
                    "F_반영일자": "",
                    "G_원료성분명": ingredient_name,
                    "H_관련 URL": record_url, # 추가된 컬럼
                    "I_관련 PDF": record_pdf_path # 추가된 컬럼
                }

            elif status == "사전예고":
                record = {
                    "A_제목": title,
                    "B_단계": "사전예고",
                    "C_시행날짜": "",
                    "D_제출날짜": "",
                    "E_예정일": plan_date_from_html if plan_date_from_html else final_plan_date,
                    "F_반영일자": "",
                    "G_원료성분명": ingredient_name,
                    "H_관련 URL": record_url, # 추가된 컬럼
                    "I_관련 PDF": record_pdf_path # 추가된 컬럼
                }

            elif status == "변경명령":
                record = {
                    "A_제목": title,
                    "B_단계": "변경명령",
                    "C_시행날짜": final_exec_date,
                    "D_제출날짜": "",
                    "E_예정일": "",
                    "F_반영일자": reflect_date_from_html if reflect_date_from_html else final_reflect_date,
                    "G_원료성분명": ingredient_name,
                    "H_관련 URL": record_url, # 추가된 컬럼
                    "I_관련 PDF": record_pdf_path # 추가된 컬럼
                }

            records.append(record)
            print(f"    📝 레코드 추가됨")

            if not any([record.get("C_시행날짜"), record.get("D_제출날짜"), record.get("E_예정일"), record.get("F_반영일자"), record.get("G_원료성분명")]):
                print(f"    ⚠️  경고: 이 항목 [{title}]에서 필요한 모든 정보 추출 실패!")
                if current_item_processed_pdf_path: # 다운로드된 PDF 파일이 있다면
                    print(f"    🔍 처리된 PDF 파일: {current_item_processed_pdf_path}")
                else:
                    print(f"    🔍 이 항목에 PDF 첨부파일이 없거나 다운로드에 실패했습니다.")


        except TimeoutException:
            print(f"    ⚠️  첨부파일 버튼을 찾을 수 없음 또는 상세 페이지 로딩 실패. 스킵합니다.")
        except Exception as detail_error:
            print(f"    ⚠️  상세 페이지 처리 중 오류 발생: {detail_error}")
        finally:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            time.sleep(0.5)

    except Exception as e:
        print(f"[{idx}] ⚠️  오류 발생: {e}")
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])

def main():
    driver = webdriver.Chrome(options=options)
    records = []
    downloaded_files = set() # 전체 세션에서 다운로드된 파일명 추적
    max_items = 50 # 기본값으로 다시 설정 (필요하면 10으로 변경하여 디버깅)

    try:
        print(f"🚀 크롤링 시작... (최근 {max_items}건만 처리)")
       
        driver.get(BASE_URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
       
        total_pages, total_items = get_total_pages(driver)
        print(f"📊 현재 데이터베이스 현황:")
        print(f"   - 총 페이지: {total_pages}페이지")
        print(f"   - 총 항목: {total_items}건")
        print(f"   - 처리 예정: 최신 {min(max_items, total_items)}건")
       
        for page_num in range(1, total_pages + 1):
            if len(records) >= max_items:
                print(f"✅ 목표 {max_items}건 도달로 처리 완료")
                break
               
            print(f"\n📄 === 페이지 {page_num}/{total_pages} 처리 중 ===")
            print(f"현재 처리된 건수: {len(records)}/{max_items}")
           
            if not navigate_to_page(driver, page_num):
                continue
           
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
           
            for idx, row in enumerate(rows, start=(page_num-1)*10 + 1):
                if len(records) >= max_items:
                    print(f"✅ 목표 {max_items}건 도달로 페이지 내 처리 중단")
                    break
                   
                process_single_item(driver, row, idx, downloaded_files, records)
            
            print(f"페이지 {page_num} 완료 - (누적: {len(records)}개)") 
           
            if len(records) >= max_items:
                break

    except Exception as e:
        print(f"❌ 전체 프로세스 오류: {e}")
    finally:
        driver.quit()

    print(f"\n📊 수집 완료!")
    print(f"목표: {max_items}건")
    print(f"실제 수집된 레코드: {len(records)}개")
    print(f"다운로드된 파일: {len(downloaded_files)}개")
   
    if records:
        df = pd.DataFrame(records).drop_duplicates()
       
        output_path = os.path.join(EXCEL_SAVE_DIR, f"변경명령_의견조회_요약_최근{len(df)}건.xlsx")
       
        # --- 변경 시작: xlsxwriter 엔진 및 하이퍼링크 포맷 사용 ---
        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            workbook = writer.book
            hyperlink_format = workbook.add_format({'font_color': 'blue', 'underline': 1})

            # 의견조회 시트
            opinion_df = df[df['B_단계'] == '의견조회']
            if not opinion_df.empty:
                opinion_final = opinion_df[['A_제목', 'B_단계', 'C_시행날짜', 'D_제출날짜', 'G_원료성분명', 'H_관련 URL', 'I_관련 PDF']].copy()
                opinion_final.columns = ['제목', '단계', '시행날짜', '제출날짜', '원료/성분명(영문)', '관련 URL', '관련 PDF']
                opinion_final.to_excel(writer, sheet_name='의견조회', index=False)
                worksheet = writer.sheets['의견조회']
                
                # '관련 URL' 컬럼에 하이퍼링크 적용
                for row_num, url in enumerate(opinion_final['관련 URL'], start=1): # 헤더 제외하고 1부터 시작
                    if url:
                        worksheet.write_url(row_num, opinion_final.columns.get_loc('관련 URL'), url, hyperlink_format, url)
                
                # '관련 PDF' 컬럼에 하이퍼링크 적용 (상대 경로로 변환)
                for row_num, pdf_path in enumerate(opinion_final['관련 PDF'], start=1):
                    if pdf_path and os.path.exists(pdf_path):
                        relative_pdf_path = os.path.relpath(pdf_path, os.path.dirname(output_path))
                        worksheet.write_url(row_num, opinion_final.columns.get_loc('관련 PDF'), relative_pdf_path, hyperlink_format, os.path.basename(pdf_path))
            
            # 사전예고 시트
            preview_df = df[df['B_단계'] == '사전예고']
            if not preview_df.empty:
                preview_final = preview_df[['A_제목', 'B_단계', 'E_예정일', 'G_원료성분명', 'H_관련 URL', 'I_관련 PDF']].copy()
                preview_final.columns = ['제목', '단계', '예정일', '원료/성분명(영문)', '관련 URL', '관련 PDF']
                preview_final.to_excel(writer, sheet_name='사전예고', index=False)
                worksheet = writer.sheets['사전예고']

                # '관련 URL' 컬럼에 하이퍼링크 적용
                for row_num, url in enumerate(preview_final['관련 URL'], start=1):
                    if url:
                        worksheet.write_url(row_num, preview_final.columns.get_loc('관련 URL'), url, hyperlink_format, url)
                
                # '관련 PDF' 컬럼에 하이퍼링크 적용 (상대 경로로 변환)
                for row_num, pdf_path in enumerate(preview_final['관련 PDF'], start=1):
                    if pdf_path and os.path.exists(pdf_path):
                        relative_pdf_path = os.path.relpath(pdf_path, os.path.dirname(output_path))
                        worksheet.write_url(row_num, preview_final.columns.get_loc('관련 PDF'), relative_pdf_path, hyperlink_format, os.path.basename(pdf_path))

            # 변경명령 시트
            command_df = df[df['B_단계'] == '변경명령']
            if not command_df.empty:
                command_final = command_df[['A_제목', 'B_단계', 'C_시행날짜', 'F_반영일자', 'G_원료성분명', 'H_관련 URL', 'I_관련 PDF']].copy()
                command_final.columns = ['제목', '단계', '시행날짜', '반영일자', '원료/성분명(영문)', '관련 URL', '관련 PDF']
                command_final.to_excel(writer, sheet_name='변경명령', index=False)
                worksheet = writer.sheets['변경명령']

                # '관련 URL' 컬럼에 하이퍼링크 적용
                for row_num, url in enumerate(command_final['관련 URL'], start=1):
                    if url:
                        worksheet.write_url(row_num, command_final.columns.get_loc('관련 URL'), url, hyperlink_format, url)
                
                # '관련 PDF' 컬럼에 하이퍼링크 적용 (상대 경로로 변환)
                for row_num, pdf_path in enumerate(command_final['관련 PDF'], start=1):
                    if pdf_path and os.path.exists(pdf_path):
                        relative_pdf_path = os.path.relpath(pdf_path, os.path.dirname(output_path))
                        worksheet.write_url(row_num, command_final.columns.get_loc('관련 PDF'), relative_pdf_path, hyperlink_format, os.path.basename(pdf_path))
        # --- 변경 종료 ---
       
        print(f"✅ 엑셀 파일 저장 완료!")
        print(f"📁 저장 경로: {output_path}")
        print(f"📋 최종 레코드 수: {len(df)}개")
       
        status_counts = df['B_단계'].value_counts()
        print(f"\n📈 상태별 통계:")
        for status_item, count_item in status_counts.items():
            print(f"  - {status_item}: {count_item}개")
       
        print(f"\n📂 저장된 파일들:")
        print(f"  📊 엑셀 파일: {output_path}")
        print(f"     - 의견조회 시트: {len(opinion_df) if 'opinion_df' in locals() else 0}건")
        print(f"     - 사전예고 시트: {len(preview_df) if 'preview_df' in locals() else 0}건")
        print(f"     - 변경명령 시트: {len(command_df) if 'command_df' in locals() else 0}건")
        print(f"  📄 다운로드된 PDF 파일들: {DOWNLOAD_DIR}")
        print(f"     (총 {len(downloaded_files)}개 PDF 파일이 다운로드되었습니다.)")
    else:
        print("❌ 수집된 데이터가 없습니다.")

if __name__ == "__main__":
    main()
