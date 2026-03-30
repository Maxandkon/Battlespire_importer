# Українською
Blender аддон для імпорту моделей та локацій з гри **An Elder Scrolls Legend: Battlespire**; має бути сумісним зі всіма версіями Blender від 3.6 до 5.1 (тестувався на 4.1); містить Українську мову, як альтернативну, у випадку якщо вона встановлена у Blender

Після встановлення потрібно вказати шлях до теки `...\An Elder Scrolls Legend Battlespire\GAMEDATA`; для використання бічної панелі, потрібно зробити приєднання архівів позв відповідну кнопку, що може зайняти певний час

Застосування:
- Імпорт .3D файлів з гри
- Бічна панель
  - Імпорт окремої локації
  - Імпорт об'єктів, що не зустрічаються на жодній локації
  - Імпорт об'єкту по назві

Аддон автоматично додає відопвідні текстури до об'єктів

# English
Blender add-on for importing models and locations from the game **An Elder Scrolls Legends: Battlespire**; should be compatible with all versions of Blender from 3.6 to 5.1 (tested on 4.1)

After installation, you must specify the path to the folder `...\An Elder Scrolls Legend Battlespire\GAMEDATA`; to use the sidebar, you must mount the archives using the corresponding button, which may take some time

Features:
- Import .3D files from the game
- Sidebar
  - Import locations
  - Import objects that unused by any location
  - Import objects by name

The add-on automatically applies the corresponding textures to objects

# Special thanks
- [ariscop](https://github.com/ariscop) – for his [battlespire-tool](https://github.com/ariscop/battlespire-tools) that was used as starting point
- [Hagrin Frost-Eye](https://en.uesp.net/wiki/User:Hagrin_Frost-Eye) – for providing save files and game guidance

# To-do list
- Find the ideal scale for the position – the current value is `0.0256`, but it seems the closest one would be something like `5/190`, as unclear how many decimal places there are
- Create data tables:
  - Of actual Locations names/usage towards ID
  - Of objects names and what they are
- Restoring original lighting – could potentially make imported locations incompatible
- Placing Water – the game adds and controls it entirely through code
- Placing of Entities and Effects – same as with water, these are dynamic values and are not fixed relative to the level
- *Suggestions*
- ...
- Get the pet for ESO "[Egg with Legs](https://en.uesp.net/wiki/Online:Half-Hatched_Guarling)", which was a cross-promotion with Castles but was never re-released; if anyone from Beth or ZOS is reading this, I've written over 90% of the Castles documentation on UESP, so I officially deserve this Egg in recognition of my dedication... or else
