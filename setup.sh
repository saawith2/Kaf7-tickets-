#!/bin/bash

# ألوان للطباعة
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                                ║${NC}"
echo -e "${BLUE}║   🎫 برنامج تثبيت بوت تذاكر Discord الخنفشاري 🚀          ║${NC}"
echo -e "${BLUE}║                    Professional Ticket Bot                     ║${NC}"
echo -e "${BLUE}║                                                                ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"

echo -e "\n${YELLOW}[1/5]${NC} فحص المتطلبات..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 غير مثبت!${NC}"
    echo "ثبّت Python من: https://www.python.org"
    exit 1
fi
echo -e "${GREEN}✅ Python3 موجود${NC}"

echo -e "\n${YELLOW}[2/5]${NC} إنشاء بيئة افتراضية..."
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠️  البيئة الافتراضية موجودة بالفعل${NC}"
else
    python3 -m venv venv
    echo -e "${GREEN}✅ تم إنشاء البيئة الافتراضية${NC}"
fi

echo -e "\n${YELLOW}[3/5]${NC} تفعيل البيئة الافتراضية..."
source venv/bin/activate
echo -e "${GREEN}✅ تم التفعيل${NC}"

echo -e "\n${YELLOW}[4/5]${NC} تثبيت المكتبات..."
pip install --upgrade pip
pip install -r requirements.txt
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ تم تثبيت جميع المكتبات${NC}"
else
    echo -e "${RED}❌ خطأ في التثبيت${NC}"
    exit 1
fi

echo -e "\n${YELLOW}[5/5]${NC} إعداد ملف البيئة..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}✅ تم إنشاء ملف .env${NC}"
    echo -e "${YELLOW}⚠️  تحتاج لتعديل الملف وإضافة التوكن!${NC}"
    echo -e "${BLUE}افتح .env وأضف توكنك${NC}"
else
    echo -e "${YELLOW}⚠️  ملف .env موجود بالفعل${NC}"
fi

echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ تم الإعداد بنجاح!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"

echo -e "\n${BLUE}📝 الخطوات التالية:${NC}"
echo -e "${YELLOW}1.${NC} عدّل ملف ${YELLOW}.env${NC} وأضف توكن البوت"
echo -e "${YELLOW}2.${NC} شغّل البوت بأحد هذه الأوامر:"
echo -e "   ${BLUE}python ticket_bot_pro.py${NC}        (الإصدار الاحترافي الكامل)"
echo -e "   ${BLUE}python ticket_bot_advanced.py${NC}   (الإصدار المتقدم)"
echo -e "   ${BLUE}python ticket_bot.py${NC}            (الإصدار الأساسي)"

echo -e "\n${BLUE}💡 نصائح:${NC}"
echo -e "${YELLOW}•${NC} استخدم ${BLUE}ticket_bot_pro.py${NC} للأداء الأفضل"
echo -e "${YELLOW}•${NC} الإصدار الاحترافي يحتوي على كل المميزات"
echo -e "${YELLOW}•${NC} قراءة الملف ${YELLOW}GUIDE_COMPLETE.md${NC} للمزيد"

echo -e "\n${GREEN}شكراً لاستخدامك البوت الخنفشاري! 🚀${NC}\n"
