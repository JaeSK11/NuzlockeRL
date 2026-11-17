# The way to Roark

Step 3.1 of [NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot): the survey the route
script is built from. The first half came from the ROM and the decomp. The
playthrough (PROGRESS.md §33) played it from the state after the first rival
battle to Roark's badge and confirmed it.

Tiles are what `gen4.read_location` reports: global on the outdoor maps,
local inside a building. Map ids are map header ids. Map events, trainers'
lines of sight, and which trainers a walk can't avoid come from the ROM
(`src/fieldmap.py`); the playthrough met each one where the ROM puts it.

## The order, as played

| # | Map (id) | What happens | Milestone |
|---|---|---|---|
| 1 | Player's house (414), Twinleaf Town (411) | After Barry 1, Mom gives the Journal and Barry's mom brings the Parcel for Barry. One scene; B ends it. The door is at (6,13), and leads out to (116,886) | `04_after_barry1_home` |
| 2 | Route 201 (342) | No trainers. North from Twinleaf, east along z=852, then north through 6 tiles of grass at x=146 (no way around) to Sandgem at x=160 | |
| 3 | Sandgem Town (418), lab (422) | A trigger across the entrance (x=164, z=842 to 847, var 16497 = 0): the professor's assistant takes the player to the lab. Rowan asks "I want to entrust you with this Pokédex": B answers no, and he asks again forever; A answers yes. Leaving the lab plays one more scene | `06_sandgem_lab_pokedex` (free in the lab at (7,6)) |
| 4 | Route 202 (343) | No catching lesson, and going home first isn't needed. Three trainers, all unavoidable (below). Ledges at z=823 and z=810 leave one way north | |
| 5 | Jubilife City (3) | Arrival trigger at (173,796), 4 wide (var 16503 = 0): the assistant's tour, which ends at (175,775). Looker turns the player back at the east exit (x=188, z=757 to 760, var 16503 = 1) until the next two steps are done | `07_jubilife_arrival` (on the trigger) |
| 6 | Trainers' School (29), door (168,776) | Barry, at (6,3), takes the Parcel; the bag gets the Town Map. No trainer in the school sees the player | `08_jubilife_school_parcel` |
| 7 | Jubilife City | Leaving the school starts the Pokétch campaign (x=172 to 176, z=776, var 16615 = 1). Each of three clowns asks a yes/no quiz (yes was right for the one read), then battles, then gives a coupon: Moe (254) at (183,769), Ronald (252) at (143,754), Mickey (253) at (164,752). The president, at (174,771), swaps the coupons for the Pokétch, and var 16503 becomes 2: the east exit opens | `09_jubilife_poketch` |
| 8 | Route 203 (344) | Barry's second battle (trainer 248): a trigger at x=196, z=757 to 760 (var 16520 = 0) spans the whole corridor, so it can't be avoided. Five trainers; two can't be avoided | `10_route203_barry2` (on the trigger) |
| 9 | Oreburgh Gate 1F (258) | Entered by walking east from (246,749). A hiker's trigger at (7,22) (var 16531 = 1) gives HM06 (Rock Smash). Two trainers, both unavoidable. The exit is (27,22), walking east | |
| 10 | Oreburgh City (45) | Arrival trigger at x=266, z=748 to 751 (var 16505 = 0): a local walks the player to the gym | `11_oreburgh_arrival` (at the city's edge) |
| 11 | Pokémon Center (48) | Healed by facing the nurse across the counter from (8,6) and pressing A through | `12_oreburgh_pokecenter` |
| 12 | Oreburgh Mine B1F (198), B2F (199) | The entrance is at x=300 to 304, z=794; B2F through (12,21). Roark stands at (18,28) behind two boulders, (19,28) and (19,29), so the way to him is the west corridor past both Workers. Talking to him plays a Rock Smash demonstration: he smashes (19,28) and leaves for the gym. No battle in the mine | `13_oreburgh_mine_roark` |
| 13 | Oreburgh Gym (47), door (282,756) | Roark at (5,3). The way up runs past both trainers (below) | `14_oreburgh_gym` (inside the door) |
| 14 | Oreburgh Gym | Roark (246) battles when talked to from (5,4). Winning gives the Coal Badge and TM39, and sets var 16503 to 3 and 16505 to 2 | `15_oreburgh_gym_before_roark`, `16_coal_badge` |

**A whiteout before any Pokémon Center** sends the player home, to (8,8) in
the house (map 414).

**Poké Balls** are in the bag from the start: the state after Barry 1 holds 20
Poké Balls, 5 Great Balls and 5 Heal Balls, and 10 Rare Candies.

## Pokémon Centers

| Town | Door | Inside |
|---|---|---|
| Sandgem Town | (177,842) | map 420 |
| Jubilife City | (180,776) | map 6 |
| Oreburgh City | (303,756) | map 48: nurse at (8,4), healed from (8,6) facing up |

A door is entered by walking into it from the street. A building's exit mat is
left by walking on toward the wall.

## Trainers on the way

Every sight trainer's script number is 2999 plus its trainer id. A trainer is
unavoidable when every walk from the map's entrance to its exit crosses its
line of sight (`fieldmap.forced_trainers`).

| Map | Trainer | Stands at | Looks, range | Avoidable |
|---|---|---|---|---|
| Route 202 | 1 Youngster Tristan | (166,813) | south, 5 | no |
| Route 202 | 3 Lass Natalie | (181,818) | south, 4 | no |
| Route 202 | 2 Bug Catcher Logan | (185,804) | south, 5 | no |
| Jubilife City | 254, 252, 253 the clowns | see above | talked to | no: the Pokétch opens the way east |
| Route 203 | 248 Barry (Cedric in the hack) | trigger at x=196 | | no |
| Route 203 | 355 Youngster Dallas | (215,756) | south, 5 | no |
| Route 203 | 4 Youngster Michael | (226,755) | south, 5 | yes |
| Route 203 | 356 Bug Catcher Sebastian | (233,759) | north, 5 | yes |
| Route 203 | 323 Lass Kaitlin | (242,755) | south, 6 | yes |
| Route 203 | 322 Lass Madeline | (246,747) | south, 2 | no: she sees the gate's door |
| Oreburgh Gate | 265 Camper Curtis | (17,26) | north, 6 | no |
| Oreburgh Gate | 329 Picnicker Diana | (24,20) | south, 6 | no |
| Oreburgh Mine B2F | 196 Worker Mason | (2,24) | east, 5 | no |
| Oreburgh Mine B2F | 195 Worker Colin | (10,28) | south, 3 | no: he stands in the corridor |
| Oreburgh Gym | 244 Scientist Jonathon | (1,17) | east, 3 | no: both ways off the top of the left stairs are in his sight |
| Oreburgh Gym | 245 Ruin Maniac Darius | (7,11) | south, 4 | no |
| Oreburgh Gym | 246 Leader Roark | (5,3) | talked to | no |

The gym's two rows come from the game, not from `fieldmap`, which reads no
floor heights (below). The playthrough fought every trainer in the table. Not met on the way: the
school kids (no Trainers' School pupil sees the player; whether they battle
when talked to wasn't checked), Clown 255, Youngster Tyler, Lass Samantha
and Lass Sarah (likely Route 204), and Galactic Puck (559).

## The Jubilife multi battle comes after Roark

A trigger at (173,743), in the north of Jubilife City, starts the multi
battle of PROGRESS.md §30 when var 16503 is 3. The only script in the ROM that
sets 16503 to 3 is the Oreburgh Gym's. With 16503 written to 3 in a test copy,
the trigger played its scene into the battle against trainer 414. In the
playthrough, beating Roark set 16503 to 3. So a run to Roark's badge never
meets it: §30's correction is itself corrected.

## The Oreburgh Gym

The gym has raised floors and a walkway that passes over floor tiles with the
same (x, z), so the ROM's collision layer shows more open floor than the
game allows, and `fieldmap` can't plan a walk here. Its tiles were found by
stepping every tile in the emulator.

- **The trainers' way:** up the stairs at x=2 (z=19 to 20) to Jonathon's
  platform, along the raised walkway to the right side (x=8 to 10), then up
  past Darius, whose sight at (7,12) can't be avoided, to Roark at (5,3).
  Talk to him from (5,4).
- **The shortcut is closed.** Vanilla also has stairs, a bridge and more
  stairs that skip both trainers (Bulbapedia's Platinum walkthrough, part 3).
  The hack puts a Rock Smash boulder at (5,15), at the foot of those stairs,
  and Rock Smash needs the Coal Badge: the boulder refuses a Pokémon that
  knows the move, and gives way once the badge's bit is set.
- The hack adds more boulders at (9,4), (1,7), (9,9), (8,10) and (10,10).
  None is on the trainers' way.

## The trainers the hack uses before Roark

From the ROM, before the playthrough. Every trainer the hack uses has
hand-set moves, and every early trainer without them is a vanilla dummy or
unused entry (PROGRESS.md §30). These are the ones with hand-set moves and
every Pokémon at level 16 or below.
The vanilla name often says where the trainer stands. The hack reuses some
dummy entries for its own trainers.

| Id | Vanilla name | In the hack | Team |
|---|---|---|---|
| 1 | `YOUNGSTER_TRISTAN` | Youngster Tristan | Zigzagoon 5, Sentret 5, Pidgey 5 |
| 2 | `YOUNGSTER_LOGAN` | Bug Catcher Logan | Weedle 6, Caterpie 6, Wurmple 7, Kricketot 7 |
| 3 | `LASS_NATALIE` | Lass Natalie | Sunkern 6, Starly 6, Poochyena 6 |
| 4 | `YOUNGSTER_MICHAEL` | Youngster Michael | Chikorita 9, Torchic 9, Squirtle 9, Rattata 10 |
| 10 | `YOUNGSTER_TYLER` | Youngster Tyler | Feebas 8, Magikarp 10, Psyduck 8 |
| 11 | `LASS_SAMANTHA` | Lass Samantha | Shellos 7, Vulpix 7, Budew 7 |
| 12 | `LASS_SARAH` | Lass Sarah | Shinx 8, Skitty 8, Meowth 7 |
| 195 | `WORKER_COLIN` | Worker Colin | Dunsparce 9, Rhyhorn 11, Slugma 11, Machop 10 |
| 196 | `WORKER_MASON` | Worker Mason | Combee 11, Phanpy 10, Geodude 10, Bidoof 12 |
| 244 | `YOUNGSTER_JONATHON` | Scientist Jonathon | Aron 12, Machop 15, Omanyte 11, Anorith 12, Onix 12 |
| 245 | `YOUNGSTER_DARIUS` | Ruin Maniac Darius | Shieldon 11, Kabuto 12, Larvitar 11, Magby 11, Nosepass 12 |
| 246 | `LEADER_ROARK` | Leader Roark | Bonsly 15, Lileep 13, Gible 14, Corsola 14, Shuckle 13, Cranidos 16 |
| 247 | `RIVAL_ROUTE_203_PIPLUP` | PkMn Trainer Cedric | Aipom 9, Taillow 9, Slakoth 9, Mankey 9, Elekid 9, Turtwig 10 |
| 248 | `RIVAL_ROUTE_203_TURTWIG` | PkMn Trainer Cedric | Aipom 9, Taillow 9, Slakoth 9, Mankey 9, Elekid 9, Chimchar 10 |
| 249 | `RIVAL_ROUTE_203_CHIMCHAR` | PkMn Trainer Cedric | Aipom 9, Taillow 9, Slakoth 9, Mankey 9, Elekid 9, Piplup 10 |
| 252 | `DUMMY_252` | Clown Ronald | Mime Jr. 8, Snubbull 8, Cleffa 8 |
| 253 | `DUMMY_253` | Clown Mickey | Pichu 8, Smoochum 8, Igglybuff 8 |
| 254 | `DUMMY_254` | Clown Moe | Makuhita 8, Happiny 10, Togepi 9 |
| 255 | `DUMMY_255` | Clown Ronald | Mime Jr. 8, Snubbull 8, Cleffa 8 |
| 265 | `CAMPER_CURTIS` | Camper Curtis | Teddiursa 10, Spoink 10, Sandshrew 9, Wingull 9, Nidoran♂ 10 |
| 322 | `LASS_MADELINE` | Lass Madeline | Mareep 10, Piplup 9, Chimchar 9, Turtwig 9 |
| 323 | `LASS_KAITLIN` | Lass Kaitlin | Snubbull 9, Growlithe 9, Electrike 9, Riolu 10 |
| 329 | `PICNICKER_DIANA` | Picnicker Diana | Eevee 10, Chingling 9, Zubat 9, Ralts 9, Nidoran♀ 10 |
| 342 | `SCHOOL_KID_HARRISON` | School Kid Harrison | Vulpix 1 |
| 345 | `SCHOOL_KID_CHRISTINE` | School Kid Christine | Sandshrew 1 |
| 355 | `YOUNGSTER_DALLAS` | Youngster Dallas | Charmander 9, Totodile 9, Treecko 9, Whismur 10 |
| 356 | `YOUNGSTER_SEBASTIAN` | Bug Catcher Sebastian | Burmy 12, Cascoon 12, Silcoon 12, Kakuna 12, Metapod 12 |
| 363 | `DUMMY_363` | School Kid Harrison | Gulpin 5 |
| 364 | `DUMMY_364` | School Kid Harrison | Poliwag 5 |
| 384 | `DUMMY_384` | School Kid Harrison | Pichu 1 |
| 402 | `DUMMY_402` | School Kid Harrison | Togepi 2 |
| 414 | `GALACTIC_GRUNT_JUBILIFE_CITY_1` | Galactic Venus | Numel 16, Stunky 16, Exeggcute 16, Koffing 16 |
| 415 | `GALACTIC_GRUNT_JUBILIFE_CITY_2` | Galactic Luna | Clefairy 16, Shuppet 16, Beldum 16, Nosepass 16 |
| 493 | `DUMMY_493` | School Kid Mickey | Gulpin 1 |
| 494 | `SWIMMER_CLAIRE` | School Kid Harrison | Bulbasaur 1 |
| 495 | `DUMMY_495` | School Kid Harrison | Spoink 1 |
| 501 | `DUMMY_501` | School Kid Harrison | Vulpix 1 |
| 502 | `DUMMY_502` | School Kid Harrison | Electrike 1 |
| 503 | `WORKER_NOEL` | School Kid Harrison | Seel 1 |
| 559 | `DRAGON_TAMER_KEEGAN` | Galactic Puck | Cleffa 1, Swinub 1, Gengar 1 |
| 613 | `LUCAS_JUBILIFE_CITY_CHIMCHAR` | PkMn Trainer Lucas | Munchlax 15, Swablu 15, Buneary 15, Grotle 16, Chimchar 15, Piplup 15 |
| 614 | `LUCAS_JUBILIFE_CITY_PIPLUP` | PkMn Trainer Lucas | Munchlax 15, Swablu 15, Buneary 15, Turtwig 15, Monferno 16, Piplup 15 |
| 615 | `LUCAS_JUBILIFE_CITY_TURTWIG` | PkMn Trainer Lucas | Munchlax 15, Swablu 15, Buneary 15, Turtwig 15, Chimchar 15, Prinplup 16 |
| 616 | `DAWN_JUBILIFE_CITY_CHIMCHAR` | PkMn Trainer Dawn | Munchlax 15, Swablu 15, Buneary 15, Grotle 16, Chimchar 15, Piplup 15 |
| 617 | `DAWN_JUBILIFE_CITY_PIPLUP` | PkMn Trainer Dawn | Munchlax 15, Swablu 15, Buneary 15, Turtwig 15, Monferno 16, Piplup 15 |
| 618 | `DAWN_JUBILIFE_CITY_TURTWIG` | PkMn Trainer Dawn | Munchlax 15, Swablu 15, Buneary 15, Turtwig 15, Chimchar 16, Prinplup 15 |
| 852 | `RIVAL_ROUTE_201_CHIMCHAR` | PkMn Trainer Cedric | Piplup 5 |

47 trainers
