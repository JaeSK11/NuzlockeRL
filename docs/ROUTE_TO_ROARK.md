# The way to Roark

Step 3.1 of [NEXT_PHASE.md](NEXT_PHASE.md#after-the-pilot): the survey the route
script is built from. This first half comes from the ROM and the decomp. The
second half, a playthrough that saves a milestone state at each beat,
confirms it and fills in what the ROM can't say: who stands where, which
battles can be walked around, and where the Pokémon Centers are.

## The expected order

Vanilla Platinum's order, from the decomp's trainer names and the hack's
trainers. **Not yet confirmed in the hack.**

1. **Twinleaf Town, Route 201, Lake Verity:** the starter, from Rowan's
   briefcase; the rival's first battle (trainers 850 to 852, by starter).
2. **Sandgem Town:** Rowan's lab and the Pokédex; a Pokémon Center.
3. **Route 202:** the catching lesson; Youngster Tristan, Bug Catcher Logan,
   Lass Natalie.
4. **Jubilife City:** a Pokémon Center. The Trainer's School, whose kids the
   hack fights at levels 1 to 5. The Pokétch clowns, whom the hack fights at
   8 to 10. The **multi battle**: the player and the professor's assistant,
   an AI partner, against two Galactic grunts at level 16.
5. **Route 203:** the rival's second battle, six Pokémon at 9 and 10;
   Youngsters Michael and Dallas, Lasses Kaitlin and Madeline, Bug Catcher
   Sebastian.
6. **Oreburgh Gate:** Camper Curtis and Picnicker Diana, if vanilla holds.
7. **Oreburgh City and Oreburgh Mine:** a Pokémon Center; Workers Colin and
   Mason; Roark in the mine, then in his gym.
8. **Oreburgh Gym:** Jonathon and Darius, then Roark.

Lass Samantha, Lass Sarah and Youngster Tyler may be on Route 204 or
elsewhere off the path; the playthrough will tell.

Two facts from earlier sections: the save state on Route 201, after the
first rival battle, already holds Poké Balls, Great Balls and Heal Balls
(PROGRESS.md §31), and no Pokémon before Roark knows Imprison, Gravity,
Encore or Torment (§27).

## The trainers the hack uses before Roark

Every trainer the hack uses has hand-set moves, and every early trainer
without them is a vanilla dummy or unused entry (PROGRESS.md §30). These
are the ones with hand-set moves and every Pokémon at level 16 or below.
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
