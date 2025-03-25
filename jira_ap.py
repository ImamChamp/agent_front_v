import re
from atlassian import Confluence
from jira import JIRA
from bs4 import BeautifulSoup


# Функция для извлечения ID страницы из URL Confluence
def extract_page_id(url: str) -> str:
    """
    Извлекает ID страницы из URL.
    Ожидается формат URL вида:
    https://your-domain.atlassian.net/wiki/spaces/SPACEKEY/pages/123456789/Название_страницы
    """
    match = re.search(r'/pages/(\d+)', url)
    if match:
        return match.group(1)
    else:
        raise ValueError("Невозможно извлечь ID страницы из URL: " + url)


# Функция для получения и обработки содержимого страницы Confluence
def get_page_content(confluence_instance, url: str) -> str:
    """
    Получает содержимое страницы Confluence по URL.
    Сначала извлекается HTML-содержимое, затем преобразуется в текст.
    """
    page_id = extract_page_id(url)
    # Расширяем ответ, чтобы получить тело страницы в формате storage (HTML)
    page = confluence_instance.get_page_by_id(page_id, expand='body.storage')
    html_content = page['body']['storage']['value']
    # Преобразуем HTML в чистый текст с помощью BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    text_content = soup.get_text(separator='\n')
    return text_content





# Функция для получения требований (постановки задачи) из Confluence
def fetch_confluence_context(confluence_instance, confluence_url: str) -> str:
    """
    Получает требования из страницы Confluence по заданному URL.
    """
    try:
        content = get_page_content(confluence_instance, confluence_url)
        return content
    except Exception as e:
        return f"Ошибка при получении информации с confluence: {str(e)}"


# Функция для создания задачи/стори в Jira
def create_jira_issue(jira_instance, user_story: dict) -> str:
    """
    Создает задачу в Jira по переданным данным user_story.
    user_story – словарь, содержащий все необходимые поля для создания задачи.
    Возвращает ключ созданной задачи или сообщение об ошибке.
    """
    try:
        issue = jira_instance.create_issue(fields=user_story)
        return issue.key
    except Exception as e:
        return f"Ошибка при создании задачи: {str(e)}"


def main():
    # ==========================
    # Настройки и аутентификация
    # ==========================
    # Параметры доступа к Confluence
    CONFLUENCE_URL = "https://queerxdisasster.atlassian.net/wiki"
    CONFLUENCE_USERNAME = "7germania7@gmail.com"
    CONFLUENCE_API_TOKEN = "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"

    # Параметры доступа к Jira
    JIRA_SERVER = "https://queerxdisasster.atlassian.net"
    JIRA_EMAIL = "7germania7@gmail.com"
    JIRA_API_TOKEN = "ATATT3xFfGF08nF1MUT2FYJTxEbAuBl8aajQ1FYyntXIo1xFGppoXriNoBJSZxz1FbQQ678LgQfArqI7vc8-spHSn-5NWZzCzdqEjo5utIDlK269XkkLIouQaAGA84v4rfYzoxpzOFuikU6XWnoeRnpZQwJnPeUR8hQRSQkXLkg2hYDCsDgloCI=A414B3DA"

    # Инициализация клиента Confluence
    confluence = Confluence(
        url=CONFLUENCE_URL,
        username=CONFLUENCE_USERNAME,
        password=CONFLUENCE_API_TOKEN
    )

    # Инициализация клиента Jira
    jira_options = {'server': JIRA_SERVER}
    jira_client = JIRA(options=jira_options, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))

    # ==========================
    # Получение контекста из Confluence
    # ==========================
    # Список URL страниц продукта (до 3)
    product_urls = [
        "https://queerxdisasster.atlassian.net/wiki/spaces/~71202020cbaa27664d44eb8a8a6123972dbd86/pages/98406/Project+Plan?force_transition=64fa49c0-c7a9-46f0-b005-48c89f914c84",
        "https://queerxdisasster.atlassian.net/wiki/spaces/~71202020cbaa27664d44eb8a8a6123972dbd86/pages/98406/Project+Plan?force_transition=64fa49c0-c7a9-46f0-b005-48c89f914c84"
    ]

    # URL страницы с постановкой задачи (требования)
    requirements_url = "https://queerxdisasster.atlassian.net/wiki/spaces/~71202020cbaa27664d44eb8a8a6123972dbd86/pages/98406/Project+Plan?force_transition=64fa49c0-c7a9-46f0-b005-48c89f914c84"



    # Извлечение требований
    requirements_content = fetch_confluence_context(confluence, requirements_url)
    print("\nТребования из Confluence:")
    print(requirements_content)

    # metadata = jira_client.createmeta(projectKeys='KAN', expand='projects.issuetypes.fields')

    # for project_data in metadata['projects']:
    #     project_key = project_data['key']
    #     if project_key == 'KAN':
    #         print(f"Доступные типы задач в проекте {project_key}:")
    #         for issuetype_data in project_data['issuetypes']:
    #             print(f"- {issuetype_data['name']}")
    # ==========================
    # Создание задач в Jira на основе user-story
    # ==========================
    # Пример объектов user-story (структуру можно расширять, добавляя любые поля, поддерживаемые Jira)
    user_stories = [
        {
            'project': {'key': 'KAN'},  # ключ проекта в Jira
            'summary': 'User Story 1: Описание функции X',
            'description':  "",
            'issuetype': {'name': 'Epic'},
            # Можно добавить дополнительные поля, например:
            # 'priority': {'name': 'High'},
            # 'labels': ['автоматизация', 'user-story']
        },
        {
            'project': {'key': 'KAN'},
            'summary': 'User Story 2: Описание функции Y',
            'description':  "",
            'issuetype': {'name': 'Task'},
            # Дополнительные поля по необходимости
        }
    ]

    # Создание задач в Jira для каждого user-story
    print("\nСоздание задач в Jira:")
    for us in user_stories:
        issue_key = create_jira_issue(jira_client, us)
        print(f"Создана задача: {issue_key}")


if __name__ == "__main__":
    main()
