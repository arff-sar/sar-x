from app import create_app
from demo_data import clear_demo_data


def main():
    app = create_app()
    with app.app_context():
        result = clear_demo_data()
        print(f"Silinen platform demo kayıt sayısı: {result.get('deleted', 0)}")
        print(f"Silinen anasayfa demo kayıt sayısı: {result.get('homepage_deleted', 0)}")
        warnings = [str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()]
        if warnings:
            print("Uyarılar:")
            for warning in warnings:
                print(f"- {warning}")


if __name__ == "__main__":
    main()
