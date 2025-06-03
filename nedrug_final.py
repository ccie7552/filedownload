import requests
from bs4 import BeautifulSoup
import time
import re
import os
from urllib.parse import urljoin, parse_qs, urlparse

class IntegratedNedrugScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.base_url = "https://nedrug.mfds.go.kr/CCBAR01F012/getList"

    # ==================== 1단계: URL 수집 ====================
    
    def get_total_info(self):
        """전체 페이지 수와 예상 항목 수를 동적으로 파악"""
        print("📊 전체 항목 수 및 페이지 수 파악 중...")
        
        try:
            # 첫 페이지 요청
            response = self.session.get(self.base_url, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 방법 1: 마지막 페이지 버튼을 클릭했을 때의 URL 파악
            test_response = self.session.get(self.base_url, params={'page': 999}, timeout=15)
            
            if '?totalPages=' in test_response.url:
                # URL에서 totalPages 추출
                parsed_url = urlparse(test_response.url)
                query_params = parse_qs(parsed_url.query)
                total_pages = int(query_params.get('totalPages', [0])[0])
                
                if total_pages > 0:
                    print(f"✅ URL에서 총 페이지 수 확인: {total_pages}페이지")
                    return total_pages, total_pages * 10  # 페이지당 10개로 추정
            
            # 방법 2: 페이지네이션에서 최대 페이지 번호 찾기
            pagination_links = soup.find_all('a', href=lambda x: x and '#list' in x)
            max_page = 1
            
            for link in pagination_links:
                text = link.get_text().strip()
                if text.isdigit():
                    max_page = max(max_page, int(text))
            
            print(f"📄 페이지네이션에서 최대 페이지: {max_page}")
            return None, None  # 순차적 탐색으로 전환
            
        except Exception as e:
            print(f"❌ 전체 정보 파악 중 오류 발생: {e}")
            return None, None

    def get_page_data(self, page_num=1):
        """특정 페이지의 데이터를 가져오는 함수"""
        try:
            params = {
                'page': page_num,
                'limit': 10
            }
            
            response = self.session.get(self.base_url, params=params, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
            
        except requests.RequestException as e:
            print(f"❌ 페이지 {page_num} 요청 중 오류 발생: {e}")
            return None

    def extract_links_from_html(self, html_content, page_num):
        """HTML에서 제목 링크들을 추출"""
        if not html_content:
            return []
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            links = []
            base_url = "https://nedrug.mfds.go.kr"
            
            table = soup.find('table')
            if not table:
                return []
            
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
            else:
                all_rows = table.find_all('tr')
                rows = all_rows[2:] if len(all_rows) > 2 else []
            
            for idx, row in enumerate(rows):
                cells = row.find_all('td')
                if len(cells) >= 2:
                    title_cell = cells[1]
                    link_tag = title_cell.find('a')
                    
                    if link_tag and link_tag.get('href'):
                        title = link_tag.get_text().strip()
                        href = link_tag.get('href')
                        
                        if href.startswith('/'):
                            full_url = base_url + href
                        else:
                            full_url = urljoin(base_url, href)
                        
                        sequence_num = cells[0].get_text().strip()
                        
                        links.append({
                            'sequence': sequence_num,
                            'title': title,
                            'url': full_url,
                            'page': page_num
                        })
            
            return links
            
        except Exception as e:
            print(f"❌ 페이지 {page_num} 파싱 중 오류 발생: {e}")
            return []

    def collect_all_urls(self):
        """모든 페이지에서 URL 수집"""
        print("🔍 최신 URL 수집을 시작합니다...")
        print("=" * 80)
        
        # 전체 페이지 수 파악 시도
        total_pages, estimated_items = self.get_total_info()
        
        all_links = []
        failed_pages = []
        
        if total_pages and estimated_items:
            # 총 페이지 수를 아는 경우
            print(f"📊 총 페이지 수: {total_pages}페이지")
            print(f"📈 예상 항목 수: {estimated_items}개")
            print("=" * 40)
            
            for page_num in range(1, total_pages + 1):
                print(f"📄 페이지 {page_num}/{total_pages} 처리 중...")
                
                html_content = self.get_page_data(page_num)
                if html_content:
                    page_links = self.extract_links_from_html(html_content, page_num)
                    if page_links:
                        all_links.extend(page_links)
                        print(f"   ✅ {len(page_links)}개 링크 수집")
                    else:
                        failed_pages.append(page_num)
                        print(f"   ⚠️ 빈 페이지")
                else:
                    failed_pages.append(page_num)
                    print(f"   ❌ 페이지 로딩 실패")
                
                time.sleep(1)
                
                if page_num % 10 == 0:
                    print(f"📊 현재까지 수집된 링크 수: {len(all_links)}개")
        else:
            # 순차적 탐색
            print("🔍 순차적 탐색 모드로 URL을 수집합니다...")
            print("⚠️ 빈 페이지가 3회 연속 나올 때까지 계속 탐색합니다.")
            print("=" * 40)
            
            page_num = 1
            consecutive_empty_pages = 0
            max_empty_pages = 3
            
            while consecutive_empty_pages < max_empty_pages:
                print(f"📄 페이지 {page_num} 처리 중...")
                
                html_content = self.get_page_data(page_num)
                if html_content:
                    page_links = self.extract_links_from_html(html_content, page_num)
                    if page_links:
                        all_links.extend(page_links)
                        consecutive_empty_pages = 0
                        print(f"   ✅ {len(page_links)}개 링크 수집")
                    else:
                        consecutive_empty_pages += 1
                        print(f"   ⚠️ 빈 페이지 감지 ({consecutive_empty_pages}/{max_empty_pages})")
                else:
                    consecutive_empty_pages += 1
                    print(f"   ❌ 페이지 로딩 실패 ({consecutive_empty_pages}/{max_empty_pages})")
                
                time.sleep(1)
                
                if page_num % 10 == 0:
                    print(f"📊 현재까지 수집된 링크 수: {len(all_links)}개")
                
                page_num += 1
                
                if page_num > 200:  # 무한루프 방지
                    print("⚠️ 최대 페이지 수(200) 도달. 수집을 종료합니다.")
                    break
        
        print("=" * 80)
        print(f"🎉 URL 수집 완료! 총 {len(all_links)}개의 링크를 찾았습니다.")
        
        if failed_pages:
            print(f"⚠️ 실패한 페이지: {len(failed_pages)}개")
        
        return all_links

    # ==================== 2단계: 상세 내용 추출 ====================
    
    def extract_detail_content(self, html_content, url):
        """상세정보 내용 추출"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        result = {
            'url': url,
            'title': '',
            'detail_content': ''
        }
        
        try:
            # 1. 제목 추출
            basic_info_table = soup.find('table')
            if basic_info_table:
                rows = basic_info_table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        header = cells[0].get_text(strip=True)
                        if header == '제목':
                            result['title'] = cells[1].get_text(strip=True)
                            break
            
            # 2. 상세정보 내용 추출
            textbox = soup.find('textbox')
            if textbox and textbox.get_text(strip=True):
                result['detail_content'] = textbox.get_text(strip=True)
            else:
                # 상세정보 테이블에서 추출
                detail_tables = soup.find_all('table')
                for table in detail_tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            header = cells[0].get_text(strip=True)
                            if header == '내용':
                                content_cell = cells[1]
                                inner_textbox = content_cell.find('textbox')
                                if inner_textbox:
                                    result['detail_content'] = inner_textbox.get_text(strip=True)
                                else:
                                    result['detail_content'] = content_cell.get_text(strip=True)
                                break
                    if result['detail_content']:
                        break
                        
        except Exception as e:
            print(f"❌ 내용 추출 중 오류 발생 ({url}): {e}")
            
        return result

    def get_page_content(self, url):
        """페이지 내용 가져오기"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.RequestException as e:
            print(f"❌ 페이지 로딩 실패 ({url}): {e}")
            return None

    def extract_details_from_urls(self, url_list, delay=1.5):
        """URL 리스트에서 상세 내용 추출"""
        print(f"\n🔍 상세 내용 추출을 시작합니다...")
        print(f"📊 총 {len(url_list)}개 URL 처리 예정")
        print(f"⏰ 예상 소요 시간: {len(url_list) * delay / 60:.1f}분")
        print("=" * 80)
        
        all_data = []
        failed_urls = []
        
        for i, link_info in enumerate(url_list, 1):
            url = link_info['url']
            title = link_info['title']
            
            print(f"📋 처리 중... ({i:4d}/{len(url_list)}) {title[:45]}...")
            
            html_content = self.get_page_content(url)
            if html_content:
                detail_info = self.extract_detail_content(html_content, url)
                if detail_info['detail_content'] or detail_info['title']:
                    detail_info['original_title'] = title
                    detail_info['sequence'] = link_info['sequence']
                    all_data.append(detail_info)
                    print(f"     ✅ 완료")
                else:
                    print(f"     ⚠️ 내용 없음")
                    failed_urls.append(url)
            else:
                print(f"     ❌ 실패")
                failed_urls.append(url)
            
            # 서버 부하 방지를 위한 지연
            if i < len(url_list):
                time.sleep(delay)
            
            # 진행 상황 중간 보고
            if i % 50 == 0:
                success_rate = len(all_data) / i * 100
                remaining_time = (len(url_list) - i) * delay / 60
                print(f"\n📊 중간 진행 상황:")
                print(f"   진행률: {i}/{len(url_list)} ({i/len(url_list)*100:.1f}%)")
                print(f"   성공: {len(all_data)}개, 실패: {len(failed_urls)}개")
                print(f"   성공률: {success_rate:.1f}%")
                print(f"   남은 시간: 약 {remaining_time:.1f}분")
                print("-" * 80)
        
        print("\n" + "=" * 80)
        print(f"🎉 상세 내용 추출 완료!")
        print(f"   ✅ 성공: {len(all_data)}개")
        print(f"   ❌ 실패: {len(failed_urls)}개")
        print(f"   📈 성공률: {len(all_data)/(len(url_list))*100:.1f}%")
        print("=" * 80)
        
        return all_data, failed_urls

    # ==================== 3단계: 결과 저장 ====================
    
    def save_to_file(self, data_list, filename="detail_context.txt"):
        """추출한 데이터를 파일로 저장"""
        try:
            # 순번으로 정렬
            try:
                data_sorted = sorted(data_list, key=lambda x: int(x['sequence']) if x['sequence'].isdigit() else 0)
            except:
                data_sorted = data_list
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("의약품안전나라 변경명령 상세정보\n")
                f.write(f"수집 일시: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")
                
                for i, data in enumerate(data_sorted, 1):
                    title = data.get('original_title') or data.get('title', '제목 없음')
                    
                    f.write(f"{data.get('sequence', i)}. {title}\n")
                    f.write(f"URL: {data['url']}\n")
                    f.write("-" * 80 + "\n")
                    
                    if data['detail_content']:
                        f.write(f"{data['detail_content']}\n")
                    else:
                        f.write("내용을 찾을 수 없습니다.\n")
                    
                    f.write("\n" + "=" * 80 + "\n\n")
                    
            print(f"💾 상세 내용이 {filename} 파일에 저장되었습니다.")
            
        except Exception as e:
            print(f"❌ 파일 저장 중 오류 발생: {e}")

    def save_urls_to_file(self, links, filename='nedrug_links.txt'):
        """URL 리스트를 파일로 저장 (백업용)"""
        try:
            # 순번으로 정렬
            try:
                links_sorted = sorted(links, key=lambda x: int(x['sequence']) if x['sequence'].isdigit() else 0)
            except:
                links_sorted = links
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("의약품안전나라 변경명령 링크 목록\n")
                f.write(f"수집 일시: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 50 + "\n\n")
                
                for link in links_sorted:
                    f.write(f"{link['sequence']}. {link['title']}\n")
                    f.write(f"{link['url']}\n")
                    f.write("-" * 50 + "\n")
            
            print(f"💾 URL 목록이 {filename} 파일에 저장되었습니다.")
            
        except Exception as e:
            print(f"❌ URL 파일 저장 중 오류 발생: {e}")

    def save_failed_urls(self, failed_urls, filename="failed_urls.txt"):
        """실패한 URL들 저장"""
        if failed_urls:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write("처리 실패한 URL 목록:\n")
                    f.write(f"생성 일시: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 50 + "\n\n")
                    for url in failed_urls:
                        f.write(f"{url}\n")
                print(f"📝 실패한 URL 목록이 {filename} 파일에 저장되었습니다.")
            except Exception as e:
                print(f"❌ 실패 URL 파일 저장 중 오류 발생: {e}")

    # ==================== 메인 실행 메서드 ====================
    
    def run_complete_process(self, detail_delay=1.5):
        """전체 프로세스 실행 - 항상 최신 URL부터 수집"""
        print("=" * 80)
        print("🚀 의약품안전나라 통합 스크래핑을 시작합니다")
        print("📅 매일 업데이트되는 최신 정보를 수집합니다")
        print("=" * 80)
        
        try:
            # 1단계: 최신 URL 수집
            print("\n[1단계] 최신 URL 수집 중...")
            all_links = self.collect_all_urls()
            
            if not all_links:
                print("❌ 수집된 URL이 없습니다. 프로그램을 종료합니다.")
                return
            
            # URL 목록 백업 저장
            self.save_urls_to_file(all_links)
            
            # 2단계: 상세 내용 추출 (메인 작업)
            print(f"\n[2단계] 상세 내용 추출 중...")
            detail_data, failed_urls = self.extract_details_from_urls(all_links, detail_delay)
            
            # 3단계: 결과 저장
            print(f"\n[3단계] 결과 저장 중...")
            if detail_data:
                self.save_to_file(detail_data)
            
            if failed_urls:
                self.save_failed_urls(failed_urls)
            
            # 최종 결과 보고
            print("\n" + "=" * 80)
            print("🎉 스크래핑 완료!")
            print("=" * 80)
            print(f"📊 전체 URL 수: {len(all_links)}개")
            print(f"✅ 상세 내용 추출 성공: {len(detail_data)}개")
            print(f"❌ 상세 내용 추출 실패: {len(failed_urls)}개")
            print(f"📈 성공률: {len(detail_data)/(len(all_links))*100:.1f}%")
            print("=" * 80)
            print("📁 생성된 파일:")
            print("   - detail_context.txt: 상세 내용 (메인 결과)")
            print("   - nedrug_links.txt: URL 목록 (백업)")
            if failed_urls:
                print("   - failed_urls.txt: 실패한 URL 목록")
            print("=" * 80)
            
            return detail_data
            
        except KeyboardInterrupt:
            print("\n⚠️ 사용자에 의해 중단되었습니다.")
        except Exception as e:
            print(f"❌ 오류 발생: {e}")

def main():
    """메인 실행 함수"""
    print("🔧 의약품안전나라 통합 스크래퍼")
    print("⚡ 항상 최신 URL부터 수집하여 당일 업데이트된 정보를 확보합니다.")
    
    scraper = IntegratedNedrugScraper()
    
    # 전체 프로세스 실행 (항상 새로운 URL 수집부터 시작)
    data = scraper.run_complete_process(detail_delay=1.5)
    
    if data:
        print(f"\n🎊 총 {len(data)}개의 문서가 성공적으로 처리되었습니다!")
        print("📋 detail_context.txt 파일에서 상세 내용을 확인하세요.")

if __name__ == "__main__":
    main()
